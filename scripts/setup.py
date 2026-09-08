"""First-run configuration. Never prints tokens to logs."""
import secrets
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    env = ROOT / ".env"
    if not env.exists():
        template = (ROOT / ".env.example").read_text(encoding="utf-8")
        env.write_text(template.replace("REPLACE_WITH_RANDOM_TOKEN", secrets.token_urlsafe(32)), encoding="utf-8")
    from backend.app.core.config import Settings
    settings = Settings()
    settings.prepare()
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
    content = ["ДЖАРВИС — ПОДКЛЮЧЕНИЕ ТЕЛЕФОНА", "", "Компьютер и телефон должны быть в одной сети.",
               "В приложении откройте «Подключение и микрофон».", "Адреса этого ПК (выберите адрес Wi-Fi / Ethernet):"]
    content += [f"http://{address}:{settings.port}" for address in addresses]
    content += ["", "Токен (скопируйте целиком):", settings.api_token.get_secret_value(),
                "", "Этот файл содержит секрет подключения. Не публикуйте его."]
    (settings.data_directory / "connection.txt").write_text("\n".join(content), encoding="utf-8")
    print("Настройка готова. Параметры подключения: data/connection.txt")


if __name__ == "__main__":
    main()
