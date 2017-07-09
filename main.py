#!/usr/bin/python2.7
# -*- coding: utf8 -*-

import os
import webapp2
import jinja2
import traceback
from collections import namedtuple
import json
from google.appengine.api import mail, app_identity, urlfetch
from planilla import fetch_planilla
from urllib import urlencode
from config import SENDER_NAME, EMAIL_TO, APP_TITLE, GRUPAL, INDIVIDUAL, RECAPTCHA_SECRET, RECAPTCHA_SITE_ID
import sys
reload(sys)
sys.setdefaultencoding("utf-8")

templates = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True,
)

File = namedtuple('File', ['content', 'filename'])

class MainPage(webapp2.RequestHandler):
    def render(self, name, params = {}):
        template = templates.get_template(name)
        self.response.write(template.render(dict(params, **{
            'title': APP_TITLE,
            'recaptcha_site_id': RECAPTCHA_SITE_ID,
        })))

    def get(self):
        planilla = fetch_planilla()
        self.render('index.html', {
            'entregas': planilla.entregas,
            'correctores_json': json.dumps(planilla.correctores),
            'entregas_json': json.dumps(planilla.entregas),
            'grupos_json': json.dumps({k: list(v) for k, v in planilla.grupos.iteritems()}),
        })

    def err(self, message):
        self.render('result.html', {'error': message})

    def get_padrones_grupo_docente(self, padron_o_grupo, tp, planilla):
        if padron_o_grupo not in planilla.correctores:
            raise Exception(u'No se encuentra el alumno o grupo {}'.format(p))
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

    def get_files(self):
        return [
            File(content=f.file.read(), filename=f.filename)
            for f in self.request.POST.getall('files')
            if hasattr(f, 'filename')
        ]

    def sendmail(self, emails_alumnos, email_docente, tp, grupo, padrones, files, body):
        body = u'\n'.join([
            tp,
            u'GRUPO {}:'.format(grupo) if grupo else 'Entrega individual:',
            u'\n'.join([u'  {}'.format(email) for email in emails_alumnos]),
            u'\n{}\n'.format(body) if body else '',
            '-- ',
            u'{} - {}'.format(APP_TITLE, self.request.url),
        ])
        mail.send_mail(
            sender='{} <noreply@{}.appspotmail.com>'.format(
                SENDER_NAME,
                app_identity.get_application_id()
            ),
            to=[EMAIL_TO, email_docente],
            cc=emails_alumnos,
            subject=u'{} - {}'.format(tp, ' - '.join(padrones)),
            body=body,
            attachments=[
                mail.Attachment(f.filename, f.content)
                for f in files
            ]
        )

    def post(self):
        try:
            self.validate_captcha()
            planilla = fetch_planilla()
            tp = self.request.POST.get('tp').upper()
            if tp not in planilla.entregas:
                raise Exception(u'La entrega {} es inválida'.format(tp))
            padrones, grupo, docente = self.get_padrones_grupo_docente(
                self.request.POST.get('padron').upper(),
                tp,
                planilla,
            )
            files = self.get_files()
            body = self.request.POST.get('body') or ''
            emails_alumnos = [planilla.emails_alumnos[p] for p in padrones]
            email_docente = planilla.emails_docentes[docente]

            self.sendmail(emails_alumnos, email_docente, tp, grupo, padrones, files, body)

            self.render('result.html', {
                'sent': {
                    'tp': tp,
                    'docente': docente,
                }
            })
        except Exception as e:
            print(traceback.format_exc())
            self.err(e.message)

    def validate_captcha(self):
        response = urlfetch.fetch(
            url='https://www.google.com/recaptcha/api/siteverify',
            payload=urlencode({
                "secret": RECAPTCHA_SECRET,
                "remoteip": self.request.remote_addr,
                "response": self.request.params.get("g-recaptcha-response"),
            }),
            method="POST",
        )
        response = json.loads(response.content)
        if not response['success']:
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

app = webapp2.WSGIApplication([
    ('/', MainPage),
], debug=True)
