import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class SlackNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def is_available(self) -> bool:
        return bool(self.webhook_url and REQUESTS_AVAILABLE)

    def send_listing(self, listing: dict, dvf_stats: Optional[dict] = None):
        if not self.is_available():
            return

        dvf = dvf_stats or listing.get("dvf_stats", {})
        price = listing.get("price", 0)
        surface = listing.get("surface_m2")
        terrain = listing.get("terrain_m2")

        surface_text = f"{surface} m²" if surface else "N/A"
        terrain_text = f"{terrain:,} m²" if terrain else "N/A"
        price_text = f"{price:,} €" if price else "N/A"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Nouvelle annonce : {listing.get('title', 'Bien immobilier')}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Prix :* {price_text}"},
                    {"type": "mrkdwn", "text": f"*Source :* {listing.get('source', '').upper()}"},
                    {"type": "mrkdwn", "text": f"*Surface :* {surface_text}"},
                    {"type": "mrkdwn", "text": f"*Terrain :* {terrain_text}"},
                    {"type": "mrkdwn", "text": f"*Lieu :* {listing.get('location', 'N/A')}"},
                ],
            },
        ]

        if listing.get("description"):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": listing["description"][:300],
                },
            })

        if dvf.get("analyse"):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Analyse DVF :* {dvf['analyse']}",
                },
            })

        if listing.get("url"):
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Voir l'annonce"},
                        "url": listing["url"],
                        "style": "primary",
                    }
                ],
            })

        try:
            _requests.post(
                self.webhook_url,
                json={"blocks": blocks},
                timeout=10,
            )
        except Exception:
            pass


class EmailNotifier:
    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str, to_email: str):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.to_email = to_email

    def is_available(self) -> bool:
        return bool(self.smtp_host and self.username and self.password and self.to_email)

    def send_listing(self, listing: dict):
        if not self.is_available():
            return

        dvf = listing.get("dvf_stats", {})
        price = listing.get("price", 0)
        surface = listing.get("surface_m2")
        terrain = listing.get("terrain_m2")

        surface_text = f"{surface} m²" if surface else "N/A"
        terrain_text = f"{terrain:,} m²" if terrain else "N/A"
        price_text = f"{price:,} €" if price else "N/A"
        dvf_analyse = dvf.get("analyse", "")
        dvf_prix_m2 = dvf.get("prix_m2_median")
        dvf_estimation = dvf.get("estimation_prix")

        html = f"""
        <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2c5282;">Nouvelle annonce immobilière</h2>
        <h3>{listing.get('title', 'Bien immobilier')}</h3>
        <table style="width:100%; border-collapse: collapse;">
            <tr><td style="padding:8px; border:1px solid #e2e8f0;"><strong>Prix</strong></td>
                <td style="padding:8px; border:1px solid #e2e8f0;">{price_text}</td></tr>
            <tr><td style="padding:8px; border:1px solid #e2e8f0;"><strong>Source</strong></td>
                <td style="padding:8px; border:1px solid #e2e8f0;">{listing.get('source', '').upper()}</td></tr>
            <tr><td style="padding:8px; border:1px solid #e2e8f0;"><strong>Surface</strong></td>
                <td style="padding:8px; border:1px solid #e2e8f0;">{surface_text}</td></tr>
            <tr><td style="padding:8px; border:1px solid #e2e8f0;"><strong>Terrain</strong></td>
                <td style="padding:8px; border:1px solid #e2e8f0;">{terrain_text}</td></tr>
            <tr><td style="padding:8px; border:1px solid #e2e8f0;"><strong>Localisation</strong></td>
                <td style="padding:8px; border:1px solid #e2e8f0;">{listing.get('location', 'N/A')}</td></tr>
        </table>
        <h4>Description</h4>
        <p>{listing.get('description', '')}</p>
        """

        if dvf_analyse:
            html += f"""
        <h4 style="color: #2c5282;">Analyse DVF</h4>
        <p>{dvf_analyse}</p>
        """
            if dvf_prix_m2:
                html += f"<p>Prix médian DVF : <strong>{dvf_prix_m2:,} €/m²</strong></p>"
            if dvf_estimation:
                html += f"<p>Estimation : <strong>{dvf_estimation:,} €</strong></p>"

        if listing.get("url"):
            html += f"""
        <p style="margin-top:20px;">
            <a href="{listing['url']}" style="background:#2c5282;color:white;padding:10px 20px;
               text-decoration:none;border-radius:4px;">Voir l'annonce</a>
        </p>
        """

        html += "</body></html>"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Immo] {listing.get('title', 'Nouvelle annonce')} — {price_text}"
        msg["From"] = self.username
        msg["To"] = self.to_email
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, self.to_email, msg.as_string())
        except Exception:
            pass


def notify_all(listing: dict, config: dict):
    slack_webhook = config.get("slack_webhook", "")
    if slack_webhook:
        notifier = SlackNotifier(slack_webhook)
        notifier.send_listing(listing)

    smtp_host = config.get("smtp_host", "")
    smtp_port = config.get("smtp_port", 587)
    smtp_user = config.get("smtp_user", "")
    smtp_password = config.get("smtp_password", "")
    email_dest = config.get("email_destinataire", "")

    if smtp_host and smtp_user and smtp_password and email_dest:
        notifier = EmailNotifier(smtp_host, smtp_port, smtp_user, smtp_password, email_dest)
        notifier.send_listing(listing)
