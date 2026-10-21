plugins { java }

group = "dev.minebridge.integration"
version = "0.1.0-dev"

repositories {
    mavenCentral()
    maven("https://repo.papermc.io/repository/maven-public/")
}

dependencies {
    compileOnly(project(":"))
    compileOnly("io.papermc.paper:paper-api:26.2.build.133-stable")
}

java { toolchain.languageVersion.set(JavaLanguageVersion.of(25)) }
tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
    options.release.set(25)
}
tasks.withType<AbstractArchiveTask>().configureEach {
    isPreserveFileTimestamps = false
    isReproducibleFileOrder = true
}
tasks.jar { archiveBaseName.set("minebridge-observer") }
tasks.processResources {
    inputs.property("version", project.version.toString())
    filesMatching("plugin.yml") { expand("version" to project.version.toString()) }
}
dependencyLocking { lockAllConfigurations() }
