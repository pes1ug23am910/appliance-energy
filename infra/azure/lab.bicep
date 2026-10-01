targetScope = 'resourceGroup'

@description('Temporary single-host laboratory. Delete the entire dedicated resource group after verification.')
param location string = resourceGroup().location
@minLength(3)
@maxLength(20)
param namePrefix string = 'appliance-smoke'
@description('Public SSH key. Private key stays on the operator machine.')
@minLength(32)
param adminSshPublicKey string
@description('One public IPv4 address with /32 prefix; no broad inbound range.')
param operatorPublicCidr string
@description('Select after checking subscription policy, quota, availability and retail prices.')
param vmSize string = 'Standard_B2as_v2'
param adminUsername string = 'appliance'
param tags object = {
  purpose: 'appliance-energy-cloud-smoke'
  lifecycle: 'temporary'
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'OperatorSSH'
        properties: {
          priority: 100
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: operatorPublicCidr
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
      {
        name: 'DenyOtherInbound'
        properties: {
          priority: 200
          access: 'Deny'
          direction: 'Inbound'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [ '10.43.0.0/16' ] }
    subnets: [
      {
        name: 'lab'
        properties: {
          addressPrefix: '10.43.1.0/24'
          networkSecurityGroup: { id: nsg.id }
          defaultOutboundAccess: false
        }
      }
    ]
  }
}
resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${namePrefix}-ip'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}
resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${namePrefix}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'lab'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: { id: publicIp.id }
          subnet: { id: '${vnet.id}/subnets/lab' }
        }
      }
    ]
  }
}
resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: '${namePrefix}-vm'
  location: location
  tags: tags
  properties: {
    hardwareProfile: { vmSize: vmSize }
    osProfile: {
      computerName: '${namePrefix}-vm'
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [ { path: '/home/${adminUsername}/.ssh/authorized_keys', keyData: adminSshPublicKey } ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        deleteOption: 'Delete'
        diskSizeGB: 64
        managedDisk: { storageAccountType: 'Premium_LRS' }
      }
    }
    networkProfile: { networkInterfaces: [ { id: nic.id, properties: { deleteOption: 'Delete' } } ] }
    diagnosticsProfile: { bootDiagnostics: { enabled: false } }
  }
}
output publicAddress string = publicIp.properties.ipAddress
output virtualMachineId string = vm.id
