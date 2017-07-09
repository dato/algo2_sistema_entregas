#!/usr/bin/python2.7
# -*- coding: utf8 -*-

import os
import webapp2
import jinja2
import traceback
from collections import namedtuple
import json
from google.appengine.api import mail, app_identity
from planilla import fetch_planilla
from config import SENDER_NAME, EMAIL_TO, APP_TITLE

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
        })))

    def get(self):
        planilla = fetch_planilla()
        self.render('index.html', {
            'alumnos': json.dumps(planilla.alumnos),
            'entregas': planilla.entregas,
        })

    def err(self, message):
        self.render('result.html', {'error': message})

    def get_padrones(self, alumnos):
        padrones = [p.upper() for p in self.request.POST.getall('padron') if p]
        for p in padrones:
            if p not in alumnos:
                raise Exception(u'No se encuentra el alumno con padrón {}'.format(p))
        return padrones

    def get_files(self):
        return [
            File(content=f.file.read(), filename=f.filename)
            for f in self.request.POST.getall('files')
            if hasattr(f, 'filename')
        ]

    def get_docentes(self, alumnos, tp, padrones):
        docentes = set(alumnos[p].get(tp, '') for p in padrones)
        warning = None
        if '' in docentes:
            warning = u'No todos los integrantes tienen un docente asignado para el {}'.format(tp)
        elif len(docentes) > 1:
            warning = u'No hay un único docente asignado para el grupo.'
        return [d for d in docentes if d], warning

    def sendmail(self, emails_alumnos, emails_docentes, tp, padrones, files, body):
        mail.send_mail(
            sender='{} <noreply@{}.appspotmail.com>'.format(
                SENDER_NAME,
                app_identity.get_application_id()
            ),
            to=[EMAIL_TO] + emails_docentes,
            cc=emails_alumnos,
            subject=u'{} - {}'.format(tp, ' - '.join(padrones)),
            body='\n\n'.join([
                'Entrega {} - {}'.format(tp, ', '.join(emails_alumnos)),
                body,
            ]),
            attachments=[
                mail.Attachment(f.filename, f.content)
                for f in files
            ]
        )

    def post(self):
        try:
            planilla = fetch_planilla()
            tp = self.request.POST.get('tp').upper()
            padrones = self.get_padrones(planilla.alumnos)
            files = self.get_files()
            body = self.request.POST.get('body') or ''
            docentes, warning = self.get_docentes(planilla.alumnos, tp, padrones)
            emails_alumnos = [planilla.emails_alumnos[p] for p in padrones]
            emails_docentes = [planilla.emails_docentes[d] for d in docentes]

            self.sendmail(emails_alumnos, emails_docentes, tp, padrones, files, body)

            self.render('result.html', {
                'warning': warning,
                'sent': {
                    'tp': tp,
                    'docentes': docentes,
                }
            })
        except Exception as e:
            print(traceback.format_exc())
            self.err(e.message)

app = webapp2.WSGIApplication([
    ('/', MainPage),
], debug=True)
