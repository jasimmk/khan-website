"""Utilities for end-to-end tests on handlers.

end-to-end tests are tests that send a url to a running server and get
a response back, and check that response to make sure it is 'correct'.

If you wish to write such tests, they should be in a file all their
own, perhaps named <file>_endtoend_test.py, and that file should start with:
   from testutil import handler_test_utils
   def setUpModule():
       handler_test_utils.start_dev_appserver()
   def tearDownModule():
       handler_test_utils.stop_dev_appserver()

TODO(csilvers): figure out if we can share this among many end-to-end
tests.  Maybe have each test that needs it advertise that fact, so it
will start up if necessary, and then somehow tell the test-runner to
call stop_dev_appserver() at test-end time.

TODO(csilvers): figure out how to reset the datastore between tests,
so there are no side-effects.

Note that these end-to-end tests are quite slow, since it's not a fast
operation to create a dev_appserver instance!

dev_appserver.py must be on your path.  The tests you run here must be
run via tools/runtests.py, so the appengine path can be set up
correctly.

Also note that the dev_appserver instance, by default, is created in a
'sandbox' with no datastore contents.
TODO(csilvers): create some 'fake' data that can be used for testing.

Useful variables:
   appserver_url: url to access the running dev_appserver instance,
      e.g. 'http://localhost:8080', or None if it's not running
   tmpdir: the directory where the dev-appserver is running from,
      also where its data files are stored
   pid: the pid the dev-appserver is running on, or None if it's not
      running
"""

import os
import shutil
import socket
import subprocess
import tempfile
import time

appserver_url = None
tmpdir = None
pid = None


def start_dev_appserver():
    """Start up a dev-appserver instance on an unused port, return its url."""
    global appserver_url, tmpdir, pid

    # Find the 'root' directory of the project the tests are being
    # run in.
    ka_root = os.getcwd()
    while ka_root != os.path.dirname(ka_root):   # we're not at /
        if os.path.exists(os.path.join(ka_root, 'app.yaml')):
            break
        ka_root = os.path.dirname(ka_root)
    if not os.path.exists(os.path.join(ka_root, 'app.yaml')):
        raise IOError('Unable to find app.yaml above cwd: %s' % os.getcwd())

    # Create a 'sandbox' directory that symlinks to ka_root,
    # except for the 'datastore' directory (we don't want to mess
    # with your actual datastore for these tests!)
    tmpdir = tempfile.mkdtemp()
    for f in os.listdir(ka_root):
        if 'datastore' not in f:
            os.symlink(os.path.join(ka_root, f),
                       os.path.join(tmpdir, f))
    os.mkdir(os.path.join(tmpdir, 'datastore'))

    # Find an unused port to run the appserver on.  There's a small
    # race condition here, but we can hope for the best.  Too bad
    # dev_appserver doesn't allow input to be port=0!
    for port in xrange(9000, 19000):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        try:
            sock.connect(('', port))
            del sock   # reclaim the socket
        except socket.error:   # means nothing is running on that socket!
            dev_appserver_port = port
            break
    else:     # for/else: if we got here, we never found a good port
        raise IOError('Could not find an unused port in range 9000-19000')

    # Start dev_appserver
    args = ['dev_appserver.py',
            '-p%s' % dev_appserver_port,
            '--use_sqlite',
            '--high_replication',
            '--address=0.0.0.0',
            ('--datastore_path=%s'
             % os.path.join(tmpdir, 'datastore/test.sqlite')),
            ('--blobstore_path=%s'
             % os.path.join(tmpdir, 'datastore/blobs')),
            tmpdir]
    # Its output is noisy, but useful, so store it in tmpdir.  Third
    # arg to open() uses line-buffering so the output is available.
    dev_appserver_file = os.path.join(tmpdir, 'dev_appserver.log')
    dev_appserver_output = open(dev_appserver_file, 'w', 1)
    print 'NOTE: Starting dev_appserver.py; output in %s' % dev_appserver_file
    pid = subprocess.Popen(args,
                            stdout=dev_appserver_output,
                            stderr=subprocess.STDOUT).pid

    # Wait for the server to start up
    time.sleep(1)          # it *definitely* takes at least a second
    for _ in xrange(40):   # wait for 8 seconds, until we give up
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        try:
            sock.connect(('', dev_appserver_port))
            break
        except socket.error:
            del sock   # reclaim the socket
            time.sleep(0.2)

    # Set the useful variables for subclasses to use
    global appserver_url
    appserver_url = 'http://localhost:%d' % dev_appserver_port

    return appserver_url


def stop_dev_appserver(delete_tmpdir=True):
    global appserver_url, tmpdir, pid

    # Try very hard to kill the dev_appserver process.
    if pid:
        try:
            os.kill(pid, 15)
            time.sleep(1)
            os.kill(pid, 15)
            time.sleep(1)
            os.kill(pid, 9)
        except OSError:   # Probably 'no such process': the kill succeeded!
            pass
        pid = None

    # Now delete the tmpdir we made.
    if delete_tmpdir and tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir = None

    # We're done tearing down!
    appserver_url = None
