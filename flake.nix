{
  description = "NarcoPolo development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
      in {
        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.uv
            pkgs.git
            pkgs.gh
            pkgs.gnumake
          ];

          env = {
            # uv uses the Nix Python instead of downloading its own
            UV_PYTHON = "${python}/bin/python3";
            UV_PYTHON_DOWNLOADS = "never";
            # manylinux wheels (numpy, scikit-image, rasterio...) need these on NixOS
            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib ];
          };

          shellHook = ''
            git config core.hooksPath .githooks
            [ -f pyproject.toml ] && uv sync --frozen --quiet
            command -v graphify >/dev/null || uv tool install "graphifyy==0.9.121" >/dev/null 2>&1
            export PATH="$HOME/.local/bin:$PATH"
          '';
        };
      });
}
