# Contributing to Minebridge

Bug reports, examples and focused pull requests are welcome. For usage, start with
the [documentation](docs/README.md). Before a large change, open an issue describing
the behavior you want to add or fix.

## Development setup

You need **Python 3.11+** and **JDK 25**. The Gradle wrapper downloads the pinned
Gradle distribution and Java dependencies on its first run. The Python library has
no runtime dependencies.

From the repository root:

```console
python -m venv .venv-dev
```

Activate the environment with `.venv-dev\Scripts\Activate.ps1` in PowerShell or
`source .venv-dev/bin/activate` in bash. Then build the Python distributions:

```console
python -m pip install --upgrade build twine
python -m build --outdir dist/python python
```

Use a fresh output directory so that it contains only the current wheel and
source distribution. The following Python snippet checks and installs that wheel,
then runs the tests outside the source tree. Save it as a temporary script in the
repository root, or run it in an interactive Python session from that directory:

```python
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path.cwd()
distributions = sorted((root / "dist/python").glob("*"))
subprocess.run([sys.executable, "-m", "twine", "check", "--strict",
                *map(str, distributions)], check=True)
wheel, = (root / "dist/python").glob("*.whl")
subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps",
                "--force-reinstall", str(wheel)], check=True)
with tempfile.TemporaryDirectory() as work:
    subprocess.run([sys.executable, "-I", "-m", "unittest", "discover",
                    "-s", str(root / "python/tests"), "-q"], cwd=work, check=True)
```

Do not set `PYTHONPATH=python/src` for this check: it should test the installed
package, including its data files and type information.

## Build and test the plugin

Linux/macOS:

```console
bash plugin/gradlew -p plugin test shadowJar --no-daemon --console=plain
```

PowerShell:

```powershell
.\plugin\gradlew.bat -p plugin test shadowJar --no-daemon --console=plain
```

The installable plugin is `plugin/build/libs/minebridge-paper-<version>.jar`.
The `-plain.jar` is not a server installation artifact. The separate `:observer`
subproject is a test plugin; do not install it on a normal server.

## Change guidelines

- Keep public method names and argument order compatible, including the familiar
  `Minecraft.create`, `setBlock` and `setBlocks` calls.
- For a wire-format change, update the protocol schemas, shared corpus, Python
  client and Java plugin together. Technical contracts live in
  [docs/contracts](docs/contracts).
- Test observable behavior. A regression test should fail for the original bug.
- Use Paper APIs on the appropriate server thread. Report success after the
  operation completes. Never automatically retry a mutation with an unknown
  outcome.
- Keep block states, physics and acknowledgement ordering intact when optimizing
  construction. Keep fixture code out of the production plugin.
- Update user documentation and examples when behavior changes.

Changes to gameplay behavior should also be checked on a disposable Paper server,
including two simultaneous Python connections. See the
[integration guide](integration/README.md). Native server testing requires the
operator to accept the Minecraft EULA; unit tests and package builds do not.

## CI and releases

GitHub Actions checks installed Python packages on Windows and Ubuntu with
Python 3.11/3.14, and builds/tests the plugin with Java 25. These checks do not
replace native Paper gameplay testing.

Release artifacts are attached to GitHub Releases. The PyPI publishing workflow
is manual and requires the repository owner to configure Trusted Publishing.
Pushing a commit or tag does not upload a package to PyPI. See the
[maintainer release guide](docs/PUBLISHING.ru.md).

Contributions are distributed under the project's [MIT license](LICENSE).
