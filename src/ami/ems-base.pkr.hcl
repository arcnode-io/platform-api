# Base AMI for the cloud EMS box: Amazon Linux 2023 + Docker + the setup wizard.
# Built by CI on a release (see .gitlab-ci.yml, job build_base_ami). The stack
# reads the resulting AMI id from SSM, never a hardcoded id.

packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = ">= 1.3.0, < 2.0.0"
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "release" {
  type        = string
  description = "The commit SHA this AMI is built from; part of the AMI name."
}

source "amazon-ebs" "ems" {
  region        = var.region
  instance_type = "t3.large"
  ssh_username  = "ec2-user"
  ami_name      = "arcnode-ems-base-${var.release}"
  source_ami_filter {
    filters = {
      name                = "al2023-ami-2023.*-x86_64"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    owners      = ["amazon"]
    most_recent = true
  }
  launch_block_device_mappings {
    device_name           = "/dev/xvda"
    volume_size           = 50
    volume_type           = "gp3"
    delete_on_termination = true
  }
}

build {
  sources = ["source.amazon-ebs.ems"]

  provisioner "file" {
    source      = "../src/wizard/"
    destination = "/tmp/wizard-src/src/wizard/"
  }

  provisioner "shell" {
    inline = [
      "sudo dnf install -y docker python3-pip",
      "sudo systemctl enable docker",
      "sudo mkdir -p /opt/arcnode-wizard-src/src",
      "sudo mv /tmp/wizard-src/src/wizard /opt/arcnode-wizard-src/src/wizard",
      "sudo touch /opt/arcnode-wizard-src/src/__init__.py",
    ]
  }
}
