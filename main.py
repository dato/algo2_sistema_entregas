#!/usr/bin/python2.7
# -*- coding: utf8 -*-

import os
import webapp2
import jinja2
import traceback

templates = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True,
)

alumnos = {
    '1234': {'TP1': 'Diego Essaya'},
}

class MainPage(webapp2.RequestHandler):
    def render(self, name, params = {}):
        template = templates.get_template(name)
        self.response.write(template.render(dict(params, **{
            'title': u'Algoritmos y Programación 1 - Entrega de TPs',
        })))

    def get(self):
        self.render('index.html')

    def err(self, message):
        self.render('result.html', {'error': message})

    def get_padrones(self):
        padrones = [p.upper() for p in self.request.POST.getall('padron') if p]
        for p in padrones:
            if p not in alumnos:
                raise Exception(u'No se encuentra el alumno con padrón {}'.format(p))
        return padrones

    def get_files(self):
        return [{
            'content': f.file.read(),
            'filename': f.filename,
        } for f in self.request.POST.getall('files')]

    def post(self):
        try:
            tp = self.request.POST.get('tp').upper()
            padrones = self.get_padrones()
            files = self.get_files()
            body = self.request.POST.get('body')

            docentes = set(alumnos[p].get(tp, '') for p in padrones)
            warning = None
            if '' in docentes:
                warning = u'Algún(os) integrantes no tienen un docente asignado para el {}'.format(tp)
            elif len(docentes) > 1:
                warning = u'No hay un único docente asignado para el grupo.'
            self.render('result.html', {
                'warning': warning,
                'sent': {
                    'tp': tp,
                    'docentes': [d for d in docentes if d],
                }
            })
        except Exception as e:
            print(traceback.format_exc())
            self.err(e.message)

app = webapp2.WSGIApplication([
    ('/', MainPage),
], debug=True)
