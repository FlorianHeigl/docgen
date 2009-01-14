#
# $Id$
#
"""
Test the ability to use dynamic plugins
"""
from twisted.trial import unittest, runner, reporter
from twisted.internet import reactor
from twisted.python.util import sibpath

from ConfigParser import SafeConfigParser
from StringIO import StringIO

from docgen.util import load_doc_plugins
from docgen.config import ProjectConfig
from docgen.ipsan_storage import IPSANStorageDesignGenerator
from docgen.commands import IPSANCommandsGenerator

from docgen import debug
import logging
log = logging.getLogger('docgen')
log.setLevel(logging.DEBUG)

config_file_data = """
[global]
# The copyright holder for all documents generated by DocGen
copyright_holder: Justin Warren

[document_plugins]
# DocumentGenerator modules to load, and the name that will be
# used to reference them.
ipsan-storage-design: docgen.ipsan_storage.IPSANStorageDesignGenerator
ipsan-network-design: docgen.ipsan_network.IPSANNetworkDesignGenerator
ipsan-storage-modipy: docgen.modipy.IPSANStorageModiPyGenerator
ipsan-storage-commands: docgen.commands.IPSANCommandsGenerator
vol-sizes: docgen.commands.IPSANVolumeSizeCommandsGenerator
ipsan-activation-advice: docgen.activation_advice.IPSANActivationAdvice
"""

class PluginsTest(unittest.TestCase):
    """
    Test some basic DocumentGenerator plugin functions
    """

    def test_load_plugins(self):
        defaults = SafeConfigParser()
        defaults.readfp(StringIO(config_file_data))
        plugins = load_doc_plugins(defaults)

        self.failUnlessEqual(len(plugins), 6)
        self.failUnless( 'vol-sizes' in plugins )
        self.failUnless( 'ipsan-storage-design' in plugins )
