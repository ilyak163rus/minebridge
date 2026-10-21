buildscript {
    configurations.classpath {
        resolutionStrategy.activateDependencyLocking()
    }
}

plugins {
    java
    id("com.gradleup.shadow") version "9.3.0"
}

group = "dev.minebridge"
version = "0.1.0-dev"
val pluginVersion = version.toString()

repositories {
    mavenCentral()
    maven("https://repo.papermc.io/repository/maven-public/")
}

dependencies {
    compileOnly("io.papermc.paper:paper-api:26.2.build.133-stable")
    implementation("com.fasterxml.jackson.core:jackson-core:2.22.4")
    testImplementation(platform("org.junit:junit-bom:5.11.4"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

java {
    toolchain.languageVersion.set(JavaLanguageVersion.of(25))
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
    options.release.set(25)
}

tasks.withType<AbstractArchiveTask>().configureEach {
    isPreserveFileTimestamps = false
    isReproducibleFileOrder = true
}

tasks.test {
    useJUnitPlatform()
    val corpus = rootProject.file("../protocol/v1/fixtures/corpus.json")
    inputs.file(corpus).withPropertyName("protocolCorpus").withPathSensitivity(PathSensitivity.RELATIVE)
    systemProperty("minebridge.fixtures", corpus.absolutePath)
}

tasks.jar {
    archiveClassifier.set("plain")
}

tasks.shadowJar {
    archiveClassifier.set("")
    relocate("com.fasterxml.jackson.core", "dev.minebridge.internal.jackson.core")
    // JPMS descriptors are not used by Paper's plugin classloader.
    exclude("module-info.class", "META-INF/versions/**/module-info.class")
}

tasks.assemble {
    dependsOn(tasks.shadowJar)
}

tasks.processResources {
    inputs.property("version", pluginVersion)
    filesMatching("plugin.yml") {
        expand("version" to pluginVersion)
    }
}

// Read-only T05 integration fixture, built explicitly and never included in the bridge JAR.
val compileWorldMetadataProbe by tasks.registering(JavaCompile::class) {
    source(rootProject.file("../integration/fixtures/world_metadata_probe/WorldMetadataProbe.java"))
    classpath = sourceSets.main.get().compileClasspath
    destinationDirectory.set(layout.buildDirectory.dir("classes/java/worldMetadataProbe"))
}

tasks.register<Jar>("worldMetadataProbeJar") {
    dependsOn(compileWorldMetadataProbe)
    archiveBaseName.set("minebridge-world-metadata-probe")
    destinationDirectory.set(layout.buildDirectory.dir("test-fixtures"))
    from(compileWorldMetadataProbe.flatMap { it.destinationDirectory })
    from(rootProject.file("../integration/fixtures/world_metadata_probe/plugin.yml"))
}

// Minimal T06 smoke fixture; the full independent integration observer remains T08.
val compileBlockSmokeProbe by tasks.registering(JavaCompile::class) {
    source(rootProject.file("../integration/fixtures/block_smoke_probe/BlockSmokeProbe.java"))
    classpath = sourceSets.main.get().compileClasspath
    destinationDirectory.set(layout.buildDirectory.dir("classes/java/blockSmokeProbe"))
}

tasks.register<Jar>("blockSmokeProbeJar") {
    dependsOn(compileBlockSmokeProbe)
    archiveBaseName.set("minebridge-block-smoke-probe")
    destinationDirectory.set(layout.buildDirectory.dir("test-fixtures"))
    from(compileBlockSmokeProbe.flatMap { it.destinationDirectory })
    from(rootProject.file("../integration/fixtures/block_smoke_probe/plugin.yml"))
}

dependencyLocking {
    lockAllConfigurations()
}

