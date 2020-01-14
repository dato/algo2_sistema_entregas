from base64 import b64encode
from email.message import Message
from email.utils import parseaddr
from smtplib import SMTP

from google.auth.transport.requests import Request  # type: ignore
from google.oauth2.credentials import Credentials  # type: ignore

from config import Settings


def sendmail(message: Message, creds: Credentials):
    """Envía un mensaje usando el SMTP de Gmail.
    """
    _, sender = parseaddr(message["From"])
    xoauth2_tok = f"user={sender}\1" f"auth=Bearer {creds.token}\1\1"
    xoauth2_b64 = b64encode(xoauth2_tok.encode("ascii")).decode("ascii")
    server = SMTP("smtp.gmail.com", 587)
    server.ehlo()
    server.starttls()
    server.ehlo()  # Se necesita EHLO de nuevo tras STARTTLS.
    server.docmd("AUTH", "XOAUTH2 " + xoauth2_b64)
    server.send_message(message)
    server.close()


def get_oauth_credentials(cfg: Settings):
    """Devuelve nuestras credenciales OAuth.
    """
    creds = Credentials(
        token=None,
        client_id=cfg.oauth_client_id,
        client_secret=cfg.oauth_client_secret.get_secret_value(),
        refresh_token=cfg.oauth_refresh_token.get_secret_value(),
        token_uri="https://accounts.google.com/o/oauth2/token",
    )
    creds.refresh(Request())  # FIXME: catch UserAccessTokenError.
    return creds
