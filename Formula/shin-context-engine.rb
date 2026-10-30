class ShinContextEngine < Formula
  desc "Local context engine for coding agents with MCP, desktop and terminal monitors"
  homepage "https://github.com/toseek-samurai/shin-context-engine"
  url "https://github.com/toseek-samurai/shin-context-engine/archive/refs/tags/v2.0.5-dev.70.tar.gz"
  version "2.0.5-dev.70"
  sha256 "e113ab4a12acbc62a2e1509e5349d554714a07f75a74861f519d84d656a37292"
  license "Apache-2.0"

  depends_on "cmake" => :build
  depends_on "ninja" => :build
  depends_on macos: :sequoia
  depends_on "openssl@3"
  depends_on "sqlite"

  resource "shin_httplib" do
    url "https://github.com/yhirose/cpp-httplib/archive/refs/tags/v0.54.1.tar.gz"
    sha256 "7310f5312e1423830d649b38ed028e9db86303a979ccbfdbd1c4b1574f422dfb"
  end

  resource "shin_toml" do
    url "https://github.com/marzer/tomlplusplus/archive/refs/tags/v3.4.0.tar.gz"
    sha256 "8517f65938a4faae9ccf8ebb36631a38c1cadfb5efa85d9a72e15b9e97d25155"
  end

  resource "shin_yaml" do
    url "https://github.com/yaml/libyaml/archive/refs/tags/0.2.5.tar.gz"
    sha256 "fa240dbf262be053f3898006d502d514936c818e422afdcf33921c63bed9bf2e"
  end

  resource "shin_ftxui" do
    url "https://github.com/ArthurSonzogni/FTXUI/archive/refs/tags/v7.0.3.tar.gz"
    sha256 "e7c62ffe19009759821b4f0f8df7f2a6fb83784c3a9f1477d81f56d3ee723c88"
  end

  resource "shin_mcp" do
    url "https://github.com/jesspig/modelcontextprotocol-cpp-sdk/archive/2304f1bb43e37034f5abf51fd9bd44f555966942.tar.gz"
    sha256 "66370718e998119f8bc17c1ac00c8e67d3e1b36ca8d88b84ef3d5aecbe468553"
  end

  resource "shin_imgui" do
    url "https://github.com/ocornut/imgui/archive/refs/tags/v1.93.0.tar.gz"
    sha256 "f7bf6bc76e5d79d40d751096663e6c5d18daf08129dd52e7f7b09e4251c8eeee"
  end

  def install
    args = std_cmake_args + %W[
      -DBUILD_TESTING=OFF
      -DSHIN_OBSERVER_SOURCE_DISCOVERY=ON
      -DSHIN_OBSERVER_MCP=ON
      -DSHIN_OBSERVER_TRAY=ON
      -DSHIN_OBSERVER_LOCAL_KIT=OFF
      -DSHIN_OBSERVER_HOMEBREW_PREFIX=#{opt_prefix}
      -DFETCHCONTENT_FULLY_DISCONNECTED=ON
      -DOPENSSL_ROOT_DIR=#{formula_opt_prefix("openssl@3")}
    ]
    resources.each do |r|
      destination = buildpath/"dependencies"/r.name
      r.stage { destination.install Dir["*"] }
      args << "-DFETCHCONTENT_SOURCE_DIR_#{r.name.upcase}=#{destination}"
    end
    system "cmake", "-S", "observer", "-B", "build", "-G", "Ninja", *args
    system "cmake", "--build", "build"
    system "cmake", "--install", "build"
    (bin/"shin-monitor").write <<~SH
      #!/bin/sh
      exec /usr/bin/open -a "#{opt_prefix}/Shin Monitor.app" --args "$@"
    SH
    (bin/"shin-monitor").chmod 0755
  end

  service do
    run [opt_bin/"shin-ce", "serve", "--registered", "--home", "#{Dir.home}/.shin-ce"]
    keep_alive true
    working_dir Dir.home
    log_path var/"log/shin-context-engine.log"
    error_log_path var/"log/shin-context-engine.log"
  end

  def caveats
    <<~EOS
      Preview package with Core, CLI/TUI, MCP, usage collector and desktop Monitor.
      Connect a project:
        shin-ce init --root /path/to/project
        shin-monitor
        shin-ce stats
      For login startup, stop the session service and use Homebrew:
        shin-ce service-stop
        brew services start toseek-samurai/tap/shin-context-engine
      Update with brew upgrade, then restart the service and persistent MCP clients.
      Homebrew owns this package; the native Shin installer/updater is disabled.
    EOS
  end

  test do
    require "json"
    project = testpath/"sample project"
    project.mkpath
    (project/"sample.cpp").write "int readLimit() { return 17; }\n"
    home = testpath/"state"
    flags = "--root #{project.to_s.shellescape} --home #{home}"
    result = JSON.parse(shell_output("#{bin}/shin-ce init #{flags} --no-service"))
    assert result.fetch("local_ready")
    result = JSON.parse(shell_output("#{bin}/shin-ce query readLimit #{flags}"))
    assert_includes result.fetch("source_context"), "return 17"
    config = JSON.parse(shell_output("#{bin}/shin-ce mcp-config --root #{project.to_s.shellescape} --home #{home}"))
    assert_equal (opt_bin/"shin-mcp").to_s, config.fetch("server").fetch("command")
    refusal = JSON.parse(shell_output("#{bin}/shin-ce update-check 2>&1", 2))
    assert_equal "package-managed-installation", refusal.fetch("error").fetch("code")
    assert_path_exists bin/"shin-context"
    assert_path_exists bin/"shin-monitor"
    assert_path_exists prefix/"Shin Monitor.app"
    refute_path_exists bin/"shin-updater"
  end
end
