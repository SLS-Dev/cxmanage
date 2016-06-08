"""Calxeda: setup.py"""


# Copyright (c) 2012-2013, Calxeda Inc.
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
# * Neither the name of Calxeda Inc. nor the names of its contributors
# may be used to endorse or promote products derived from this software
# without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDERS OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
# OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
# TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF
# THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.


from setuptools import setup
import os

travis_build = os.environ.get('TRAVIS_BUILD_NUMBER')
if travis_build is None:
    travis_build = ''
else:
    travis_build = ".dev" + travis_build

def get_version():
    """ Parse __init__.py to find the package version """
    for line in open("cxmanage_api/__init__.py"):
        key, delim, value = line.partition("=")
        if key.strip() == "__version__" and delim == "=":
            return value.strip().strip("'\"") + travis_build
    raise Exception("Failed to parse cxmanage package version from __init__.py")

setup(
    name='cxmanage',
    version=get_version(),
    packages=[
        'cxmanage_api',
        'cxmanage_api.cli',
        'cxmanage_api.cli.commands',
        'cxmanage_api.tests'
    ],
    scripts=['scripts/cxmanage', 'scripts/sol_tabs', 'scripts/cxmux', 'run_tests'],
    description='Calxeda Management Utility',
    # NOTE: As of right now, the pyipmi version requirement needs to be updated
    # at the top of scripts/cxmanage as well.
    install_requires=[
                        'tftpy',
                        'pexpect',
                        'pyipmi>=0.11.0',
                        'argparse',
                        'unittest-xml-reporting',
                        'mock'
    ],
    extras_require={
        'docs': ['sphinx', 'cloud_sptheme'],
    },
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2.7']
)
