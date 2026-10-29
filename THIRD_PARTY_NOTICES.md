# Third-party components

Minebridge's own code is available under the [MIT License](LICENSE).
Dependency licenses remain the licenses of their respective owners.

The Paper plugin bundles **Jackson Core 2.22.4**, relocated from
`com.fasterxml.jackson.core` to `dev.minebridge.internal.jackson.core`.
Jackson Core is licensed under Apache License 2.0; its upstream license and
notice files are retained in the plugin JAR.

- Source and license: https://github.com/FasterXML/jackson-core
- Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0

Paper API is a compile-time dependency and the Paper server is installed
separately. Neither the Paper server JAR nor Minecraft server/world files are
included in Minebridge releases. See https://github.com/PaperMC/Paper for Paper's
license notices. Test-only observers and integration fixtures are not bundled
in the production plugin or Python package.

The source repository includes the Gradle Wrapper, distributed by Gradle under
Apache License 2.0. Its script copyright/license headers are retained.
Gradle distributions and local dependency caches are not included in releases.
See https://github.com/gradle/gradle/blob/master/LICENSE.

The Python package has no third-party runtime dependencies. Generated catalogs
record identifiers and properties from the pinned Paper 26.2 build 133;
provenance and generation tools are kept in `catalogs/` and `tools/`.

Minecraft is a trademark of Mojang Studios. Minebridge is an independent
project and is not an official Mojang or Microsoft product.
