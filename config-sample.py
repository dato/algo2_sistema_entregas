from collections import OrderedDict

GRUPAL = "g"
INDIVIDUAL = "i"

SPREADSHEET_ID = '...'
ENTREGAS = OrderedDict([('TP0', INDIVIDUAL), ('VD', INDIVIDUAL), ('Pila', INDIVIDUAL) ])
SENDER_NAME = 'Entregas Algoritmos 1'
EMAIL_TO = 'tps.7540rw@gmail.com'
APP_TITLE = 'Algoritmos y Programación 1 - Entrega de TPs'

SERVICE_ACCOUNT_CREDENTIALS = {
  "type": "service_account",
  "project_id": "...",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----...-----END PRIVATE KEY-----\n",
  "client_email": "...",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://accounts.google.com/o/oauth2/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "..."
}

RECAPTCHA_SITE_ID = '...'
RECAPTCHA_SECRET = '...'

TEST = False
