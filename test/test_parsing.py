#
# $Id$
#
"""
Test parsing of XML files
"""
import os.path
from lxml import etree

from twisted.trial import unittest, runner, reporter
from twisted.internet import reactor
from twisted.python.util import sibpath

from ConfigParser import RawConfigParser
from StringIO import StringIO

from docgen.options import BaseOptions
from docgen.project import Project

from docgen import debug
import logging
log = logging.getLogger('docgen')
log.setLevel(logging.DEBUG)

XML_FILE_LOCATION = sibpath(__file__, "xml")
TESTCONF = sibpath(__file__, "docgen_test.conf")

class ParserTest(unittest.TestCase):
    """
    Test the ability to parse various XML files
    """
    
    def setUp(self):
        optparser = BaseOptions()
        optparser.parseOptions(['dummyfile.xml', '--debug=%s' % logging._levelNames[log.level].lower()])

        self.defaults = RawConfigParser()
        configfiles = self.defaults.read(TESTCONF)

    def test_parse_minimal(self):
        """
        Test parsing of minimal XML file
        """
        xmlfile = "minimal_parsable_config.xml"
        filepath = os.path.join(XML_FILE_LOCATION, xmlfile)
        tree = etree.parse(filepath)
        project = Project()
        project.configure_from_node(tree.getroot(), self.defaults, None)
        
    def test_parse_drhostexports(self):
        """
        Test parsing of dr host exports syntax
        """
        xmlfile = "drhostexport_test.xml"
        filepath = os.path.join(XML_FILE_LOCATION, xmlfile)
        tree = etree.parse(filepath)
        project = Project()
        project.configure_from_node(tree.getroot(), self.defaults, None)
        
    def test_parse_clustered_nearstore(self):
        """
        Test parsing of clustered nearstore syntax
        """
        xmlfile = "clustered_nearstore.xml"
        filepath = os.path.join(XML_FILE_LOCATION, xmlfile)
        tree = etree.parse(filepath)
        project = Project()
        project.configure_from_node(tree.getroot(), self.defaults, None)
        
