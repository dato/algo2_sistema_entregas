import json
import traceback
import urlfetch
from collections import namedtuple
from urllib.parse import urlencode

from flask import Flask
from flask import render_template
from flask import request

from config import SENDER_NAME, EMAIL_TO, APP_TITLE, GRUPAL, RECAPTCHA_SECRET, RECAPTCHA_SITE_ID, TEST
from planilla import fetch_planilla

app = Flask(__name__)

# templates = jinja2.Environment(
#     loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')),
#     extensions=['jinja2.ext.autoescape'],
#     autoescape=True,
# )

File = namedtuple('File', ['content', 'filename'])


@app.route('/', methods=['GET'])
def get():
    planilla = fetch_planilla()
    return render('index.html', {
        'alumnos': json.dumps(planilla.emails_alumnos),
    })


def render(name, params={}):
    return render_template(name, **dict(params, **{
        'title': APP_TITLE,
        'recaptcha_site_id': RECAPTCHA_SITE_ID,
        'test': TEST,
    }))


@app.errorhandler(Exception)
def err(message):
    return render('result.html', {'error': message})


def get_padrones_grupo_docente(padron_o_grupo, tp, planilla):
    if padron_o_grupo not in planilla.correctores:
        raise Exception(u'No se encuentra el alumno o grupo {}'.format(padron_o_grupo))
    if planilla.entregas[tp] == GRUPAL:
        if padron_o_grupo in planilla.grupos:
            grupo = padron_o_grupo
        else:
            grupo = buscar_grupo(planilla.grupos, padron_o_grupo)
        padrones = planilla.grupos[grupo]
        docente = get_docente(planilla.correctores, grupo, tp)
    else:
        grupo = None
        padrones = set([padron_o_grupo])
        docente = get_docente(planilla.correctores, padron_o_grupo, tp)
    return padrones, grupo, docente


def get_files():
    return [
        File(content=f.file.read(), filename=f.filename)
        for f in request.files
        if hasattr(f, 'filename')
    ]


def sendmail(email_alumno, email_docente, tp, grupo, padrones, files, body):
    email = [
        ('sender', '{} <noreply@{}.appspotmail.com>'.format(
            SENDER_NAME,
            app_identity.get_application_id()
        )),
        ('subject', u'{} - {}'.format(tp, ' - '.join(padrones))),
        ('to', [EMAIL_TO]),
        ('reply_to', email_alumno),
        ('body', u'\n'.join([
            tp,
            u'GRUPO {}:'.format(grupo) if grupo else 'Entrega individual:',
            u'\n'.join([email_alumno]),
            u'\n{}\n'.format(body) if body else '',
            '-- ',
            u'{} - {}'.format(APP_TITLE, request.url),
        ])),
        ('attachments', [
            mail.Attachment(f.filename, f.content)
            for f in files
        ]),
    ]
    if not TEST:
        mail.send_mail(**dict(email))
    return email


@app.route('/', methods=['POST'])
def post():
    try:
        validate_captcha()
        planilla = fetch_planilla()
        tp = request.form['tp'].upper()
        if tp not in planilla.entregas:
            raise Exception(u'La entrega {} es inválida'.format(tp))
        files = get_files()
        grupo = ''
        body = request.form['body'] or ''
        padrones = [request.form['padron']]
        email_alumno = planilla.emails_alumnos[padrones[0]]
        email_docente = ''
        email = sendmail(email_alumno, email_docente, tp, grupo, padrones, files, body)

        return render('result.html', {
            'sent': {
                'tp': tp,
                'email': u'\n'.join(u'[[{}]]: {}'.format(k, str(v)) for k, v in email) if TEST else None,
            },
        })
    except Exception as e:
        print(traceback.format_exc())
        err(e.message)


def validate_captcha():
    response = urlfetch.fetch(
        url='https://www.google.com/recaptcha/api/siteverify',
        params=urlencode({
            "secret": RECAPTCHA_SECRET,
            "remoteip": request.remote_addr,
            "response": request.form["g-recaptcha-response"],
        }),
        method="POST",
    )

    if not response.json['success']:
        raise Exception('Falló la validación del captcha')


def buscar_grupo(grupos, padron):
    for grupo, padrones in grupos.iteritems():
        if padron in padrones:
            return grupo
    raise Exception(u'No se encuentra el grupo para el padron {}'.format(padron))


def get_docente(correctores, padron_o_grupo, tp):
    if tp not in correctores[padron_o_grupo]:
        raise Exception(u'No hay un corrector asignado para la entrega {}'.format(tp))
    return correctores[padron_o_grupo][tp]
