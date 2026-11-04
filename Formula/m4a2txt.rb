class M4a2txt < Formula
  desc "Offline audio transcription, English translation and subtitle export"
  homepage "https://github.com/QSOLKCB/M4A2TXT"
  head "https://github.com/QSOLKCB/M4A2TXT.git", branch: "main"
  license all_of: ["Apache-2.0", "MIT"]

  depends_on "cmake" => :build
  depends_on "ffmpeg"
  depends_on "python@3.13"
  depends_on "python-tk@3.13"
  depends_on :macos

  resource "whisper" do
    url "https://github.com/ggml-org/whisper.cpp.git",
        revision: "d1be6fde11ac6e0407606b4e42fe72d34add8037"
  end

  def install
    libexec.install "m4a-scribe", "m4a2txt"
    resource("whisper").stage do
      system "cmake", "-S", ".", "-B", "build", *std_cmake_args,
             "-DBUILD_SHARED_LIBS=OFF", "-DWHISPER_BUILD_TESTS=OFF", "-DWHISPER_BUILD_IS_DEV=OFF",
             "-DWHISPER_BUILD_SERVER=OFF", "-DWHISPER_CURL=OFF",
             "-DGGML_RPC=OFF", "-DGGML_BACKEND_DL=OFF", "-DGGML_METAL=OFF",
             "-DGGML_CUDA=OFF", "-DGGML_NATIVE=OFF", "-DGGML_OPENMP=OFF"
      system "cmake", "--build", "build", "--target", "whisper-cli", "--parallel", ENV.make_jobs
      (libexec/"m4a-scribe/bin").install "build/bin/whisper-cli"
      (pkgshare/"licenses").install "LICENSE" => "whisper-LICENSE"
    end
    (bin/"m4a2txt").write <<~SH
      #!/bin/sh
      export SCRIBE_DATA_HOME="${SCRIBE_DATA_HOME:-$HOME/Library/Application Support/m4a2txt}"
      export PATH="#{Formula["ffmpeg"].opt_bin}:$PATH"
      exec "#{Formula["python@3.13"].opt_bin}/python3.13" "#{libexec}/m4a2txt" "$@"
    SH
  end

  test do
    assert_match "--task", shell_output("#{bin}/m4a2txt --cli --help")
    assert_match "FFmpeg: available", shell_output("#{bin}/m4a2txt --check")
    system libexec/"m4a-scribe/bin/whisper-cli", "--version"
  end
end
