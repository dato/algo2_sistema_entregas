#!/usr/bin/python2.7
# -*- coding: utf8 -*-

import os
import webapp2
import jinja2

templates = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True,
)

class MainPage(webapp2.RequestHandler):
    def render(self, name, *args):
        template = templates.get_template(name)
        self.response.write(template.render(*args))

    def get(self):
        self.render('index.html', {
            'title': u'Algoritmos y Programación 1 - Entrega de TPs',
        })

app = webapp2.WSGIApplication([
    ('/', MainPage),
], debug=True)
