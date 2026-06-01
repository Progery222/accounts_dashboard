"""Dump TV emu config JSON from server file (for backup / copy to another host)."""
from django.core.management.base import BaseCommand

from accounts.tv_emu_config import load_tv_emu_config, save_tv_emu_config


class Command(BaseCommand):
    help = "Show or import tv_broadcast_emu.json (TV emulation settings shared by all clients)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--import",
            dest="import_path",
            metavar="FILE",
            help="Import config from JSON file",
        )

    def handle(self, *args, **options):
        import_path = options.get("import_path")
        if import_path:
            import json
            from pathlib import Path

            data = json.loads(Path(import_path).read_text(encoding="utf-8"))
            path = save_tv_emu_config(data)
            self.stdout.write(self.style.SUCCESS(f"Imported -> {path}"))
            return

        cfg = load_tv_emu_config()
        if cfg is None:
            self.stdout.write("No config on server (config is null).")
            return
        import json

        self.stdout.write(json.dumps(cfg, ensure_ascii=False, indent=2))
