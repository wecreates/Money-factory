
output "instance_id" {
  value = oci_core_instance.farm.id
}
output "public_ip" {
  value = oci_core_instance.farm.public_ip
}
