#!/usr/bin/python2.7
# -*- coding: utf8 -*-

import os
import webapp2
import jinja2
import traceback
from collections import namedtuple
import json
from correctores import alumnos
from google.appengine.api import mail, app_identity

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
            'title': u'Algoritmos y Programación 1 - Entrega de TPs',
        })))

    def get(self):
        self.render('index.html', {'alumnos': json.dumps(alumnos)})

    def err(self, message):
        self.render('result.html', {'error': message})

    def get_padrones(self):
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

    def get_docentes(self, tp, padrones):
        docentes = set(alumnos[p].get(tp, '') for p in padrones)
        warning = None
        if '' in docentes:
            warning = u'No todos los integrantes tienen un docente asignado para el {}'.format(tp)
        elif len(docentes) > 1:
            warning = u'No hay un único docente asignado para el grupo.'
        return [d for d in docentes if d], warning

    def sendmail(self, docentes, tp, padrones, files, body):
        mail.send_mail(
            sender='Entregas Algoritmos 1 <noreply@{}.appspotmail.com>'.format(
                app_identity.get_application_id()
            ),
            to=['tps.7540rw@gmail.com'],
            subject=u'{} - {}'.format(tp, ' - '.join(padrones)),
            body=body,
            attachments=[
                mail.Attachment(f.filename, f.content)
                for f in files
            ]
        )

    def post(self):
        try:
            tp = self.request.POST.get('tp').upper()
            padrones = self.get_padrones()
            files = self.get_files()
            body = self.request.POST.get('body') or ''
            docentes, warning = self.get_docentes(tp, padrones)

            self.sendmail(docentes, tp, padrones, files, body)

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
