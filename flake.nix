{
  description = "Terminal-based temperature graph monitoring via lm-sensors";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;
      in {
        packages.default = python.pkgs.buildPythonApplication {
          pname = "temptop";
          version = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;
          pyproject = true;

          src = self;

          build-system = [ python.pkgs.setuptools ];

          makeWrapperArgs = [ "--prefix" "PATH" ":" "${pkgs.lm_sensors}/bin" ];

          meta = with pkgs.lib; {
            description = "A Linux terminal hardware temperature monitor and Braille grapher";
            license = licenses.mit;
            mainProgram = "temptop";
            platforms = platforms.linux;
          };
        };

        devShells.default = pkgs.mkShell {
          packages = [ python pkgs.lm_sensors ];
        };
      });
}
