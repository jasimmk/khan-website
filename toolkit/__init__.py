from __future__ import absolute_import
import os
import logging

from request_handler import RequestHandler
from google.appengine.ext.webapp import template

class Toolkit(RequestHandler):

    def get(self):
        
        self.render_jinja2_template('toolkit/view_toolkit.html', {})

