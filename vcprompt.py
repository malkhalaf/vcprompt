#!/usr/bin/env python
from __future__ import with_statement
from subprocess import Popen, PIPE
import optparse
import os
import re
import sqlite3
import sys

__version__ = (0, 0, 2)

FORMAT = '%s:%b'
SYSTEMS = []
UNKNOWN = '(unknown)'


# unknown environment variable
if 'VCPROMPT_UNKNOWN' in list(os.environ.keys()):
    if os.environ['VCPROMPT_UNKNOWN']:
        UNKNOWN = os.environ['VCPROMPT_UNKNOWN']

# foamtting environment variable
if 'VCPROMPT_FORMAT' in list(os.environ.keys()):
    if os.environ['VCPROMPT_FORMAT']:
        FORMAT = os.environ['VCPROMPT_FORMAT']


def sorted_alpha(sortme, unique=False):
    upper = [x for x in sortme if x.isupper()]
    lower = [x for x in sortme if x.islower()]
    digit = [x for x in sortme if x.isdigit()]
    if unique:
        upper = list(set(upper))
        lower = list(set(lower))
        digit = list(set(digit))
    return lower + upper + digit


def vcs(function):
    SYSTEMS.append(function)
    return function


def vcprompt(path, string):
    paths = os.path.abspath(path).split('/')
    prompt = None
    while paths:
        path = '/'.join(paths)
        paths.pop()
        if prompt:
            return prompt
        for vcs in SYSTEMS:
            prompt = vcs(path, string)
            if prompt:
                break
    return ''


def version():
    return '.'.join(map(str, __version__))


def main():
    # parser
    parser = optparse.OptionParser("usage: %prog FORMAT [OPTIONS]",
                                   version=version())
    parser.add_option('-f', '--format', dest='format',
                      default=FORMAT, help='The format string to use.')
    parser.add_option('-p', '--path', dest='path',
                      default='.', help='The path to run vcprompt on.')

    # parse!
    options, args = parser.parse_args()

    sys.stdout.write(vcprompt(options.path, options.format))


@vcs
def bzr(path, string):
    file = os.path.join(path, '.bzr/branch/last-revision')
    if not os.path.exists(file):
        return None

    branch = hash = status = UNKNOWN

    # local revision number
    if re.search('%(r|h)', string):
        with open(file, 'r') as f:
            hash = f.read().strip().split(' ', 1)[0]


    # status
    if '%i' in string:
        command = 'bzr status'
        process = Popen(command.split(), stdout=PIPE)
        output = process.communicate()[0]
        returncode = process.returncode

        if not returncode:
            # the list of headers in 'bzr status' output
            headers = {'added': 'A',
                       'modified': 'M',
                       'removed': 'R',
                       'renamed': 'V',
                       'kind changed': 'K',
                       'unknown': '?'}
            headers_regex = '%s:' % '|'.join(headers.keys())

            status = ''
            for line in output.split('\n'):
                line = line.strip()
                if re.match(headers_regex, line):
                    header = line.split(':')[0]
                    status = '%s%s' % (status, headers[header])

            status = sorted_alpha(status)

    # branch
    # TODO figure out something more correct
    string = string.replace('%b', os.path.basename(path))
    string = string.replace('%h', hash)
    string = string.replace('%r', hash)
    string = string.replace('%i', status)
    string = string.replace('%s', 'bzr')
    return string


@vcs
def cvs(path, string):
    # Stabbing in the dark here
    # TODO make this not suck
    file = os.path.join(path, 'CVS/')
    if not os.path.exists(file):
        return None

    branch = revision = UNKNOWN

    string = string.replace('%s', 'cvs')
    string = string.replace('%b', branch)
    string = string.replace('%r', revision)
    return string


@vcs
def darcs(path, string):
    # It's almost a given that everything in here is
    # going to be wrong
    file = os.path.join(path, '_darcs/hashed_inventory')
    if not os.path.exists(file):
        return None

    hash = branch = status = UNKNOWN
    # hash
    if re.search('%(h|r)', string):
        with open(file, 'r') as f:
            size, hash = f.read().strip().split('\n')[0].split('-')
            hash = hash[:7]

    # branch
    # darcs doesn't have in-repo local branching (yet)
    # http://bugs.darcs.net/issue555
    # until it does, or I can think of something better, this'll have to do
    branch = os.path.basename(path)

    # status
    if '%i' in string:
        status = ''
        command = 'darcs whatsnew -l'
        process = Popen(command.split(), stdout=PIPE, stderr=PIPE)
        output = process.communicate()[0]
        returncode = process.returncode

        if not returncode:
            for line in output.split('\n'):
                code = line.split(' ')[0]
                status = '%s%s' % (status, code)
            status = sorted_alpha(status)

    # formatting
    string = string.replace('%b', branch)
    string = string.replace('%h', hash)
    string = string.replace('%r', hash)
    string = string.replace('%i', status)
    string = string.replace('%s', 'darcs')
    return string


@vcs
def fossil(path, string):
    # In my five minutes of playing with Fossil this looks OK
    file = os.path.join(path, '_FOSSIL_')
    if not os.path.exists(file):
        return None

    branch = hash = UNKNOWN

    # all this just to get the repository file :(
    repository = None
    try:
        query = "SELECT value FROM vvar where name = 'repository'"
        conn = sqlite3.connect(file)
        c = conn.cursor()
        c.execute(query)
        repository = c.fetchone()[0]
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

    if repository:
        # get the hash. we need this to get the current trunk
        _rid = None
        if re.search('%(b|h|r)', string):
            try:
                query = """SELECT uuid, rid FROM blob
                           ORDER BY rid DESC LIMIT 1"""
                conn = sqlite3.connect(repository)
                c = conn.cursor()
                c.execute(query)
                hash, _rid = c.fetchone()
                hash = hash[:7]
            except sqlite3.OperationalError:
                pass
            finally:
                conn.close()

           # now we grab the branch
            try:
                query = """SELECT value FROM tagxref WHERE rid = %d and
                           value is not NULL LIMIT 1 """ % _rid
                conn = sqlite3.connect(repository)
                c = conn.cursor()
                c.execute(query)
                branch = c.fetchone()[0]
            except sqlite3.OperationalError:
                pass
            finally:
                conn.close()


    # parse out formatting string
    string = string.replace('%b', branch)
    string = string.replace('%h', hash)
    string = string.replace('%r', hash)
    string = string.replace('%s', 'fossil')
    return string


@vcs
def git(path, string):
    file = os.path.join(path, '.git/')
    if not os.path.exists(file):
        return None

    branch = hash = status = UNKNOWN
    # the current branch is required to get the hash
    if re.search('%(b|r|h)', string):
        branch_file = os.path.join(file, 'HEAD')
        with open(branch_file, 'r') as f:
            line = f.read()

            # check if we're currently running on a branch
            if re.match('^ref: refs/heads/', line.strip()):
                branch = (line.split('/')[-1] or UNKNOWN).strip()
            # we're running with a detached head (submodule?)
            else:
                branch = os.listdir(os.path.join(file, 'refs/heads'))[0]

        # hash/revision
        if re.search('%(r|h)', string):
            hash_file = os.path.join(file, 'refs/heads/%s' % branch)
            with open(hash_file, 'r') as f:
                hash = f.read().strip()[0:7]

    # status
    status = UNKNOWN
    if '%i' in string:
        command = 'git status --short'
        process = Popen(command.split(), stdout=PIPE, stderr=PIPE)
        output = process.communicate()[0]
        returncode = process.returncode

        # only process if ``git status`` has the --short option
        if not returncode:
            status = ''
            for line in output.split('\n'):
                code = line.strip().split(' ')[0]
                status = '%s%s' % (status, code)

    if status != UNKNOWN:
        status = sorted_alpha(status)

    # formatting
    string = string.replace('%b', branch)
    string = string.replace('%h', hash)
    string = string.replace('%r', hash)
    string = string.replace('%i', status)
    string = string.replace('%s', 'git')
    return string


@vcs
def hg(path, string):
    files = ['.hg/branch', '.hg/undo.branch', '.hg/bookmarks.current']
    file = None
    for f in files:
        f = os.path.join(path, f)
        if os.path.exists(f):
            file = f
            break
    if not file:
        return None

    branch = revision = hash = status = UNKNOWN

    # changeset ID or global hash
    if re.search('%(r|h)', string):
        cache_file = os.path.join(path, '.hg/tags.cache')
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                revision, hash = f.read().split()
                hash = hash[:7]

    # branch
    if '%b' in string:
        with open(file, 'r') as f:
            branch = f.read().strip()

    # status
    status = UNKNOWN
    if '%i' in string:
        command = 'hg status'
        process = Popen(command.split(), stdout=PIPE)
        output = process.communicate()[0]
        returncode = process.returncode
        if not returncode:
            status = ''
            for line in output.split('\n'):
                code = line.strip().split(' ')[0]
                status = '%s%s' % (status, code)

            # sort the string to make it all pretty like
            status = sorted_alpha(status)

    string = string.replace('%b', branch)
    string = string.replace('%h', hash)
    string = string.replace('%r', revision)
    string = string.replace('%i', status)
    string = string.replace('%s', 'hg')
    return string


@vcs
def svn(path, string):
    file = os.path.join(path, '.svn/entries')
    if not os.path.exists(file):
        return None

    branch = revision = status = UNKNOWN

    # branch
    command = 'svn info %s' % path
    process = Popen(command.split(), stdout=PIPE, stderr=PIPE)
    output = process.communicate()[0]
    returncode = process.returncode

    if not returncode:
        # compile some regexes
        branch_regex = re.compile('((tags|branches)|trunk)')
        revision_regex = re.compile('^Revision: (?P<revision>\d+)')

        for line in output.split('\n'):
            # branch
            if '%b' in string:
                if re.match('URL:', line):
                    matches = re.search(branch_regex, line)
                    if matches:
                        branch = matches.groups(0)[0]

            # revision/hash
            if re.search('%(r|h)', string):
                if re.match('Revision:', line):
                    matches = re.search(revision_regex, line)
                    if 'revision' in matches.groupdict():
                        revision = matches.group('revision')

    # status
    if '%i' in string:
        command = 'svn status'
        process = Popen(command, shell=True, stdout=PIPE)
        output = process.communicate()[0]
        returncode = process.returncode

        if not returncode:
            status = ''
            for line in output.split('\n'):
                code = line.strip().split(' ')[0]
                status = '%s%s' % (status, code)

            status = sorted_alpha(status)

    # formatting
    string = string.replace('%r', revision)
    string = string.replace('%h', revision)
    string = string.replace('%b', branch)
    string = string.replace('%i', status)
    string = string.replace('%s', 'svn')
    return string


if __name__ == '__main__':
    main()
