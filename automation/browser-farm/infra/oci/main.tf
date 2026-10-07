
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

provider "oci" {
  tenancy_ocid = var.tenancy_ocid
  user_ocid    = var.user_ocid
  fingerprint  = var.fingerprint
  private_key  = var.private_key
  region       = var.region
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "farm" {
  compartment_id = var.compartment_ocid
  display_name   = "cyzor-browser-farm-vcn"
  cidr_blocks    = ["10.77.0.0/16"]
  dns_label      = "cyzorfarm"
}

resource "oci_core_internet_gateway" "farm" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.farm.id
  enabled        = true
  display_name   = "cyzor-browser-farm-igw"
}

resource "oci_core_route_table" "farm" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.farm.id
  display_name   = "cyzor-browser-farm-routes"

  route_rules {
    network_entity_id = oci_core_internet_gateway.farm.id
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
  }
}

resource "oci_core_security_list" "farm" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.farm.id
  display_name   = "cyzor-browser-farm-security"

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 22
      max = 22
    }
    description = "SSH bootstrap only"
  }

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 80
      max = 80
    }
    description = "HTTP migration edge"
  }

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 443
      max = 443
    }
    description = "HTTPS migration edge"
  }
}

resource "oci_core_subnet" "farm" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.farm.id
  cidr_block        = "10.77.1.0/24"
  display_name      = "cyzor-browser-farm-subnet"
  dns_label         = "workers"
  route_table_id    = oci_core_route_table.farm.id
  security_list_ids = [oci_core_security_list.farm.id]
  prohibit_public_ip_on_vnic = false
}

resource "oci_core_instance" "farm" {
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  compartment_id      = var.compartment_ocid
  display_name        = var.instance_name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_gb
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.farm.id
    assign_public_ip = true
    display_name     = "cyzor-browser-farm-vnic"
  }

  source_details {
    source_type = "image"
    source_id   = data.oci_core_images.ubuntu.images[0].id
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(<<-CLOUD
      #cloud-config
      package_update: true
      packages:
        - git
        - docker.io
        - docker-compose-v2
        - curl
        - ca-certificates
      runcmd:
        - systemctl enable --now docker
        - mkdir -p /opt/cyzor
        - git clone https://github.com/wecreates/Money-factory.git /opt/cyzor/Money-factory
        - cp /opt/cyzor/Money-factory/automation/browser-farm/.env.example /opt/cyzor/Money-factory/automation/browser-farm/.env
        - chown -R ubuntu:ubuntu /opt/cyzor
    CLOUD
    )
  }

  lifecycle {
    ignore_changes = [source_details[0].source_id]
  }
}
