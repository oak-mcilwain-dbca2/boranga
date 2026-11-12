# your_app/management/commands/crawl_endpoints.py
import logging
import re
import warnings

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.core.management.base import BaseCommand
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver

try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
except ImportError:
    openpyxl = None

IGNORE_PREFIXES = [
    "/admin/reversion/revision/",
    "/api/schema",
    "/api/docs",
    "/swagger",
    "/redoc",
]

EXPECTED_FAILURES = [
    "/sentry-debug/",
]


class MemoryLogHandler(logging.Handler):
    """Captures ERROR log records emitted during a single request."""

    def __init__(self):
        super().__init__()
        self.buffer = []

    def emit(self, record):
        self.buffer.append(self.format(record))

    def get_and_clear(self):
        content = "\n".join(self.buffer).strip()
        self.buffer.clear()
        return content


class Command(BaseCommand):
    help = "Crawls all GET endpoints and writes tracebacks to crawl_errors.log"

    def add_arguments(self, parser):
        parser.add_argument("--output", default="crawl_results.xlsx", help="XLSX report filename")
        parser.add_argument("--log-file", default="crawl_errors.log", help="Error log filename")

    def handle(self, *args, **options):
        output_file = options["output"]
        error_log_file = options["log_file"]

        # 1. Silence WARNING, INFO, DEBUG logs and stdlib warnings
        logging.disable(logging.WARNING)
        warnings.filterwarnings("ignore")

        # 2. Attach in-memory logger to capture stack traces from DRF custom_exception_handler
        memory_handler = MemoryLogHandler()
        memory_handler.setLevel(logging.ERROR)
        memory_handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s]: %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(memory_handler)

        client = Client()

        # Log in via session directly to bypass signals
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        if user:
            session = client.session
            session[SESSION_KEY] = user._meta.pk.value_to_string(user)
            session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
            session[HASH_SESSION_KEY] = user.get_session_auth_hash()
            session.save()
            self.stdout.write(self.style.SUCCESS(f"Logged in as {user}"))

        # 3. Extract & Clean URLs
        raw_routes = []

        def extract_urls(url_list, prefix=""):
            for entry in url_list:
                if isinstance(entry, URLPattern):
                    raw_routes.append(prefix + str(entry.pattern))
                elif isinstance(entry, URLResolver):
                    extract_urls(entry.url_patterns, prefix + str(entry.pattern))

        extract_urls(get_resolver().url_patterns)

        cleaned_patterns = set()
        for route in raw_routes:
            if "format>" in route or "<format>" in route:
                continue

            cleaned = route.replace("^", "").replace("$", "").replace("\\", "")
            cleaned = re.sub(r"/\?", "/", cleaned)
            cleaned = re.sub(r"\[[^\]]+\]\+?", "", cleaned)
            cleaned = "/" + re.sub(r"/+", "/", cleaned).lstrip("/")

            is_parameterized = any(token in cleaned for token in ["<", "(?P", "("])

            if not is_parameterized:
                cleaned_patterns.add(cleaned)
            else:
                # Fix: Replace (?P<name>regex) FIRST, then <name> tags
                sample_route = re.sub(r"\(\?P<[^>]+>[^)]+\)", "1", cleaned)
                sample_route = re.sub(r"<[^>]+>", "1", sample_route)
                sample_route = re.sub(r"/+", "/", sample_route)
                cleaned_patterns.add(sample_route)

        patterns = sorted(list(cleaned_patterns))
        self.stdout.write(f"Crawling {len(patterns)} endpoints...\n")

        results = []
        error_log_entries = []

        for path in patterns:
            if any(path.startswith(prefix) for prefix in IGNORE_PREFIXES):
                self.stdout.write(self.style.WARNING(f"SKIP : {path}"))
                results.append([path, "N/A", "SKIPPED", "In IGNORE_PREFIXES"])
                continue

            is_expected_fail = any(path.startswith(prefix) for prefix in EXPECTED_FAILURES)

            # Clear memory buffer before making request
            memory_handler.get_and_clear()

            try:
                response = client.get(path, follow=False)
                status = response.status_code
                captured_traceback = memory_handler.get_and_clear()

                if status >= 500:
                    if is_expected_fail:
                        self.stdout.write(self.style.WARNING(f"EXP-FAIL [{status}]: {path}"))
                        results.append([path, status, "EXPECTED_FAIL", "HTTP 500 (Expected)"])
                    else:
                        self.stdout.write(self.style.ERROR(f"FAIL [{status}]: {path}"))
                        results.append([path, status, "FAIL", captured_traceback[:150] or "HTTP 500"])

                        # Save full traceback for error log file
                        error_log_entries.append(
                            f"{'=' * 80}\nURL: {path} [HTTP {status}]\n{'=' * 80}\n"
                            f"{captured_traceback or 'No traceback captured.'}\n\n"
                        )
                elif status == 404:
                    self.stdout.write(self.style.WARNING(f"404  [{status}]: {path}"))
                    results.append([path, status, "NOT_FOUND", "404 with dummy parameter"])
                elif 300 <= status < 400:
                    self.stdout.write(self.style.SUCCESS(f"REDIR[{status}]: {path}"))
                    results.append([path, status, "REDIRECT", response.headers.get("Location", "")])
                else:
                    self.stdout.write(self.style.SUCCESS(f"OK   [{status}]: {path}"))
                    results.append([path, status, "OK", ""])

            except Exception as e:
                captured_traceback = memory_handler.get_and_clear()
                err_msg = str(e)
                if is_expected_fail:
                    self.stdout.write(self.style.WARNING(f"EXP-FAIL [EXCEPTION]: {path}"))
                    results.append([path, "EXCEPTION", "EXPECTED_FAIL", err_msg])
                else:
                    self.stdout.write(self.style.ERROR(f"ERROR: {path} -> {err_msg}"))
                    results.append([path, "EXCEPTION", "FAIL", err_msg])
                    error_log_entries.append(
                        f"{'=' * 80}\nURL: {path} [UNCAUGHT EXCEPTION]\n{'=' * 80}\n{captured_traceback or err_msg}\n\n"
                    )

        # 4. Write crawl_errors.log
        if error_log_entries:
            with open(error_log_file, "w") as f:
                f.writelines(error_log_entries)
            self.stdout.write(
                self.style.ERROR(f"\n{len(error_log_entries)} error tracebacks saved to: {error_log_file}")
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nNo errors recorded!"))

        # 5. Export to XLSX
        if openpyxl:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Postgres 17 Crawl Results"

            headers = ["Endpoint URL", "Status Code", "Result", "Details"]
            ws.append(headers)

            header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_num)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="left")

            fills = {
                "OK": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
                "REDIRECT": PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid"),
                "FAIL": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
                "EXPECTED_FAIL": PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
                "NOT_FOUND": PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"),
                "SKIPPED": PatternFill(start_color="E0E0E0", end_color="E0E0E0", fill_type="solid"),
            }

            for row_idx, row_data in enumerate(results, start=2):
                ws.append(row_data)
                result_val = row_data[2]
                if result_val in fills:
                    ws.cell(row=row_idx, column=3).fill = fills[result_val]

            ws.auto_filter.ref = f"A1:D{len(results) + 1}"
            ws.freeze_panes = "A2"

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 80)

            wb.save(output_file)
            self.stdout.write(self.style.SUCCESS(f"Spreadsheet saved to: {output_file}"))
