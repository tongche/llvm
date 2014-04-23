import os
import sys

import Test
import TestRunner
import Util

kIsWindows = sys.platform in ['win32', 'cygwin']

class GoogleTest(object):
    def __init__(self, test_sub_dir, test_suffix):
        self.test_sub_dir = os.path.normcase(str(test_sub_dir)).split(';')
        self.test_suffix = str(test_suffix)

        # On Windows, assume tests will also end in '.exe'.
        if kIsWindows:
            self.test_suffix += '.exe'

    def getGTestTests(self, path, litConfig, localConfig):
        """getGTestTests(path) - [name]

        Return the tests available in gtest executable.

        Args:
          path: String path to a gtest executable
          litConfig: LitConfig instance
          localConfig: TestingConfig instance"""

        try:
            lines = Util.capture([path, '--gtest_list_tests'],
                                 env=localConfig.environment)
            if kIsWindows:
              lines = lines.replace('\r', '')
            lines = lines.split('\n')
        except:
            litConfig.error("unable to discover google-tests in %r" % path)
            raise StopIteration

        nested_tests = []
        for ln in lines:
            if not ln.strip():
                continue

            prefix = ''
            index = 0
            while ln[index*2:index*2+2] == '  ':
                index += 1
            while len(nested_tests) > index:
                nested_tests.pop()

            ln = ln[index*2:]
            if ln.endswith('.'):
                nested_tests.append(ln)
            else:
                yield ''.join(nested_tests) + ln

    def getTestsInDirectory(self, testSuite, path_in_suite,
                            litConfig, localConfig):
        source_path = testSuite.getSourcePath(path_in_suite)

        # Check for the one subdirectory (build directory) tests will be in.
        if not '.' in self.test_sub_dir:
            dirs = [f for f in os.listdir(source_path) \
                    if os.path.normcase(f) in self.test_sub_dir]
        else:
            dirs = '.'

        for dirname in dirs:
            filepath = os.path.join(source_path, dirname)
            if not os.path.isdir(filepath):
                continue

            for subfilename in os.listdir(filepath):
                if subfilename.endswith(self.test_suffix):
                    execpath = os.path.join(filepath, subfilename)

                    # Discover the tests in this executable.
                    for name in self.getGTestTests(execpath, litConfig,
                                                   localConfig):
                        if dirname != '.':
                            testPath = path_in_suite + (dirname, subfilename, name)
                        else:
                            testPath = path_in_suite + (subfilename, name)
                        yield Test.Test(testSuite, testPath, localConfig)

    def execute(self, test, litConfig):
        testPath,testName = os.path.split(test.getSourcePath())
        while not os.path.exists(testPath):
            # Handle GTest parametrized and typed tests, whose name includes
            # some '/'s.
            testPath, namePrefix = os.path.split(testPath)
            testName = os.path.join(namePrefix, testName)

        cmd = [testPath, '--gtest_filter=' + testName]
        if litConfig.useValgrind:
            cmd = litConfig.valgrindArgs + cmd

        out, err, exitCode = TestRunner.executeCommand(
            cmd, env=test.config.environment)

        if not exitCode:
            return Test.PASS,''

        return Test.FAIL, out + err

###

class FileBasedTest(object):
    def _isTestSupported(self, filepath, localConfig):
        for ln in open(filepath):
            if 'REQUIRES:' in ln:
                items = ln[ln.index('REQUIRES:') + 9:].split(',')
                requires = [[ss.strip() for ss in s.split('|')] for s in items]
                missing_required_features = [f for f in requires
                        if not localConfig.available_features.intersection(f)]
                if missing_required_features:
                    return False
            elif 'END.' in ln:
                # Check for END. lines.
                if ln[ln.index('END.'):].strip() == 'END.':
                    break
        return True

    def getTestsInDirectory(self, testSuite, path_in_suite,
                            litConfig, localConfig):
        source_path = testSuite.getSourcePath(path_in_suite)
        for filename in os.listdir(source_path):
            # Ignore dot files and excluded tests.
            if (filename.startswith('.') or
                filename in localConfig.excludes):
                continue

            filepath = os.path.join(source_path, filename)
            if os.path.isdir(filepath):
                continue

            base,ext = os.path.splitext(filename)
            if ext not in localConfig.suffixes:
                continue

            if litConfig.excludeUnsupported:
                if not self._isTestSupported(filepath, localConfig):
                    continue

            yield Test.Test(testSuite, path_in_suite + (filename,),
                            localConfig)

    def getTmpBase(self, test, litConfig):
        """getTmpBase - get base name for temporary files for the test"""
        execdir,execbase = os.path.split(test.getExecPath())
        tmpDir = os.path.join(execdir, 'Output')
        tmpBase = os.path.join(tmpDir, execbase)
        if test.index is not None:
            tmpBase += '_%d' % test.index
        return tmpBase

    def applyScriptSubstitutions(self, test, litConfig, script, tmpBase,
                                 normalize_slashes=False,
                                 extra_substitutions=[]):
        """applyScriptSubstitutions - apply substitutions to a test script"""

        sourcepath = test.getSourcePath()
        sourcedir = os.path.dirname(sourcepath)
        execdir,execbase = os.path.split(test.getExecPath())
        tmpDir = os.path.dirname(tmpBase)

        # Normalize slashes, if requested.
        if normalize_slashes:
            sourcepath = sourcepath.replace('\\', '/')
            sourcedir = sourcedir.replace('\\', '/')
            tmpDir = tmpDir.replace('\\', '/')
            tmpBase = tmpBase.replace('\\', '/')

        # We use #_MARKER_# to hide %% while we do the other substitutions.
        substitutions = list(extra_substitutions)
        substitutions.extend([('%%', '#_MARKER_#')])
        substitutions.extend(test.config.substitutions)
        substitutions.extend([('%s', sourcepath),
                              ('%S', sourcedir),
                              ('%p', sourcedir),
                              ('%{pathsep}', os.pathsep),
                              ('%t', tmpBase + '.tmp'),
                              ('%T', tmpDir),
                              # FIXME: Remove this once we kill DejaGNU.
                              ('%abs_tmp', tmpBase + '.tmp'),
                              ('#_MARKER_#', '%')])

        # Apply substitutions to the script.  Allow full regular
        # expression syntax.  Replace each matching occurrence of regular
        # expression pattern a with substitution b in line ln.
        def processLine(ln):
            # Apply substitutions
            for a,b in substitutions:
                if kIsWindows:
                    b = b.replace("\\","\\\\")
                ln = re.sub(a, b, ln)

            # Strip the trailing newline and any extra whitespace.
            return ln.strip()
        script = map(processLine, script)

        return script

    def getTestScript(self, test, litConfig, default_script = []):
        """parseIntegratedTestScript - Scan an LLVM/Clang style integrated test
        script and extract the lines to 'RUN' as well as 'XFAIL' and 'XTARGET'
        information.
        """

        # Collect the test lines from the script.
        script = []
        xfails = []
        xtargets = []
        requires = []
        rfails = []
        for ln in open(test.getSourcePath()):
            if 'RUN:' in ln:
                # Isolate the command to run.
                index = ln.index('RUN:')
                ln = ln[index+4:]

                # Trim trailing whitespace.
                ln = ln.rstrip()

                # Collapse lines with trailing '\\'.
                if script and script[-1][-1] == '\\':
                    script[-1] = script[-1][:-1] + ln
                else:
                    script.append(ln)
            elif 'XFAIL:' in ln:
                items = ln[ln.index('XFAIL:') + 6:].split(',')
                xfails.extend([s.strip() for s in items])
            elif 'XTARGET:' in ln:
                items = ln[ln.index('XTARGET:') + 8:].split(',')
                xtargets.extend([s.strip() for s in items])
            elif 'REQUIRES:' in ln:
                items = ln[ln.index('REQUIRES:') + 9:].split(',')
                requires.extend([
                    [ss.strip() for ss in s.split('|')] for s in items])
            elif 'RFAIL:' in ln:
                items = ln[ln.index('RFAIL:') + 6:].split(',')
                rfails.extend([
                    [ss.strip() for ss in s.split('&')] for s in items])
            elif 'END.' in ln:
                # Check for END. lines.
                if ln[ln.index('END.'):].strip() == 'END.':
                    break

        if not script:
            script = list(default_script)

        # Verify the script contains a run line.
        if not script:
            return (Test.UNRESOLVED, "Test has no run line!")

        # Check for unterminated run lines.
        if script[-1][-1] == '\\':
            return (Test.UNRESOLVED, "Test has unterminated run lines (with '\\')")

        # Check that we have the required features:
        missing_required_features = [f for f in requires
                if not test.config.available_features.intersection(f)]
        if missing_required_features:
            msg = ', '.join([' | '.join(f) for f in missing_required_features])
            return (Test.UNSUPPORTED,
                    "Test requires the following features: %s" % msg)

        def isExpectedFail(xfails, xtargets, target_triple):
            # Check if any xfail matches this target.
            for item in xfails:
                if item == '*' or item in target_triple:
                    break
            else:
                return False

            # If so, see if it is expected to pass on this target.
            #
            # FIXME: Rename XTARGET to something that makes sense, like XPASS.
            for item in xtargets:
                if item == '*' or item in target_triple:
                    return False

            return True

        def isExpectedRFail(rfails, available_features):
            for item in rfails:
                if item == ['*'] or test.config.available_features.issuperset(item):
                    return True
            return False

        isXFail = isExpectedFail(xfails, xtargets, test.suite.config.target_triple)
        isXFail = isXFail or isExpectedRFail(rfails, test.config.available_features)
        return (Test.PASS, script, isXFail)

class ShTest(FileBasedTest):
    def __init__(self, execute_external = False, default_script = []):
        self.execute_external = execute_external
        self.default_script = list(default_script)

    def execute(self, test, litConfig):
        execdir = os.path.dirname(test.getExecPath())
        tmpBase  = self.getTmpBase(test, litConfig)

        res = self.getTestScript(test, litConfig, self.default_script)
        if len(res) == 2:
            return res
        s, script, isXFail = res

        script = self.applyScriptSubstitutions(test, litConfig, script,
                tmpBase, normalize_slashes=self.execute_external)

        return TestRunner.executeShTest(test, litConfig, script,
                                        isXFail, tmpBase, execdir,
                                        self.execute_external)

class TclTest(FileBasedTest):
    def __init__(self, ignoreStdErr=False):
        self.ignoreStdErr = ignoreStdErr
        
    def execute(self, test, litConfig):
        litConfig.ignoreStdErr = self.ignoreStdErr

        execdir = os.path.dirname(test.getExecPath())
        tmpBase  = self.getTmpBase(test, litConfig)

        res = self.getTestScript(test, litConfig)
        if len(res) == 2:
            return res
        s, script, isXFail = res

        script = self.applyScriptSubstitutions(test, litConfig, script,
                tmpBase, normalize_slashes=TestRunner.kIsWindows)

        return TestRunner.executeTclTest(test, litConfig, script,
                                         isXFail, tmpBase, execdir)

###

import re
import tempfile

class OneCommandPerFileTest:
    # FIXME: Refactor into generic test for running some command on a directory
    # of inputs.

    def __init__(self, command, dir, recursive=False,
                 pattern=".*", useTempInput=False,
                 allowStdout=False, allowStderr=False):
        if isinstance(command, str):
            self.command = [command]
        else:
            self.command = list(command)
        if dir is not None:
            dir = str(dir)
        self.dir = dir
        self.recursive = bool(recursive)
        self.pattern = re.compile(pattern)
        self.useTempInput = useTempInput
        self.allowStdout = allowStdout
        self.allowStderr = allowStderr

    def getTestsInDirectory(self, testSuite, path_in_suite,
                            litConfig, localConfig):
        dir = self.dir
        if dir is None:
            dir = testSuite.getSourcePath(path_in_suite)

        for dirname,subdirs,filenames in os.walk(dir):
            if not self.recursive:
                subdirs[:] = []

            subdirs[:] = [d for d in subdirs
                          if (d != '.svn' and
                              d not in localConfig.excludes)]

            for filename in filenames:
                if (filename.startswith('.') or
                    not self.pattern.match(filename) or
                    filename in localConfig.excludes):
                    continue

                path = os.path.join(dirname,filename)
                suffix = path[len(dir):]
                if suffix.startswith(os.sep):
                    suffix = suffix[1:]
                test = Test.Test(testSuite,
                                 path_in_suite + tuple(suffix.split(os.sep)),
                                 localConfig)
                # FIXME: Hack?
                test.source_path = path
                yield test

    def createTempInput(self, tmp, test):
        abstract

    def execute(self, test, litConfig):
        if test.config.unsupported:
            return (Test.UNSUPPORTED, 'Test is unsupported')

        cmd = list(self.command)

        # If using temp input, create a temporary file and hand it to the
        # subclass.
        if self.useTempInput:
            tmp = tempfile.NamedTemporaryFile(suffix='.cpp')
            self.createTempInput(tmp, test)
            tmp.flush()
            cmd.append(tmp.name)
        elif hasattr(test, 'source_path'):
            cmd.append(test.source_path)
        else:
            cmd.append(test.getSourcePath())

        out, err, exitCode = TestRunner.executeCommand(cmd)

        if not exitCode and (self.allowStdout or not out.strip()) and \
                            (self.allowStderr or not err.strip()):
            status = Test.PASS
        else:
            status = Test.FAIL

        if status == Test.FAIL or litConfig.showAllOutput:
            # Try to include some useful information.
            report = """Command: %s\n""" % ' '.join(["'%s'" % a
                                                     for a in cmd])
            if self.useTempInput:
                report += """Temporary File: %s\n""" % tmp.name
                report += "--\n%s--\n""" % open(tmp.name).read()
            report += """Command Output (stdout):\n--\n%s--\n""" % out
            report += """Command Output (stderr):\n--\n%s--\n""" % err
        else:
            report = ""

        return status, report

class SyntaxCheckTest(OneCommandPerFileTest):
    def __init__(self, compiler, dir, extra_cxx_args=[], *args, **kwargs):
        cmd = [compiler, '-x', 'c++', '-fsyntax-only'] + extra_cxx_args
        OneCommandPerFileTest.__init__(self, cmd, dir,
                                       useTempInput=1, *args, **kwargs)

    def createTempInput(self, tmp, test):
        print >>tmp, '#include "%s"' % test.source_path
