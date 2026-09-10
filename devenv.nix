{ pkgs, ... }:
{
  languages.clojure.enable = true;
  languages.opentofu.enable = true;
  packages = with pkgs; [ ansible awscli2 babashka curl jq openssh openssl postgresql rclone
    (python3.withPackages (ps: [ ps.boto3 ps.pyyaml ])) ];
}
