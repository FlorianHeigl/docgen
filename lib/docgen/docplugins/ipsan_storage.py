##
## $Id: ipsan_storage.py 182 2008-11-13 00:33:48Z daedalus $
## IPSAN Storage Design generation components
## 

import sys
import textwrap

from datetime import datetime
from zope.interface import Interface
from string import Template
from lxml import etree

from docgen.base import DocBookGenerator
from netapp_commands import NetAppCommandsGenerator

import logging
from docgen import debug
log = logging.getLogger('docgen')

__version__ = '$Revision: 182 $'

class IPSANStorageDesignGenerator(DocBookGenerator):
    """
    An IPSANDesignGenerator emits an XML DocBook schema for a design
    document for the IP-SAN.
    """

    introduction = Template('''
  <chapter>
    <title>Introduction</title>
    <para>This document provides an IP-SAN design for the project &project.title;.</para>
    <section>
      <title>Background</title>
      $background_text
    </section>

    <section>
      <title>Audience</title>
      <para>This document is intended to be read by:
        <itemizedlist>
          <listitem>
            <para>The stakeholders of the project.</para>
          </listitem>
          <listitem>
            <para>The host build teams for the project.</para>
          </listitem>
          <listitem>
            <para>The team responsible for the IP-SAN architecture.</para>
          </listitem>
          <listitem>
            <para>The team responsible for the activation of the storage.</para>
          </listitem>

        </itemizedlist>
      </para>

    </section>

    $assumptions
    $scope
    $how_to_use
    $typographical_conventions
 </chapter>
''')

    assumptions = Template('''<section>
    <title>Assumptions</title>
  <para>This storage design assumes the following:</para>
  <para>
    <itemizedlist>
      <listitem>
        <para>Snap Reserve space for each volume is set at a default
        of 20% of the size of the active volume. If the active filesystem
        in the volume changes to a great degree, there is a possibility
        that data within this reserve space may start consuming part of
        the active filesystem. Pro-active support is required to monitor
        reserve utilisation.
        </para>
      </listitem>

      $assumption_list

    </itemizedlist>
  </para>
</section>''')

    scope = Template('''<section>
    <title>Scope</title>
    <para>This document is limited to the NFS, CIFS and iSCSI based storage
    needs for the &project.title; project, and this document provides
    the information in the following areas:
    </para>
    <para>
      <itemizedlist>
        <listitem>
          <para>The storage topology for the project.
          </para>
        </listitem>

        <listitem>
          <para>The storage layout and mapping to individual hosts.
          </para>
        </listitem>

        <listitem>
          <para>The configuration of volumes, qtrees and vFiler resources.
          </para>
        </listitem>

        $scope_list

      </itemizedlist>
    </para>
  </section>
''')

    how_to_use = Template('''
    <section>
      <title>How To Use This Document</title>
      <para>This document assumes the existence of an associated Customer Network Storage
Design document for &project.title;. The network storage design document contains the IP-
SAN configuration details for this project.</para>

<para>In addition to the storage design for &project.title;, this document contains the necessary
activation instructions to configure the storage on the storage appliances and
present the storage to the project hosts.</para>

    <note>
      <para>For specific instructions on how to activate and configure the storage on the project
hosts, please refer to the specific IP-SAN Host Activation Guides. Project hosts must be
configured to access IP-SAN storage by following the instructions and content provided in
the host activation guides.
      </para>
    </note>
  </section>
  ''')

    typographical_conventions = Template('''
    <section>
      <title>Typographical Conventions</title>
      <para>The following typographical conventions are used within this document:
      </para>

      <itemizedlist>
        <listitem>
          <para>Ordinary text will appear like this.
          </para>
        </listitem>

        <listitem>
          <para>Filenames, computer program names, and similar text will <filename>appear like this</filename>.
          </para>
        </listitem>

        <listitem>
          <screen>Computer output, program listings, file contents, etc. will appear like this.
          </screen>
        </listitem>

        <listitem>
          <note>
            <para>Informational notes will appear like this.</para>
          </note>
        </listitem>

        <listitem>
          <warning>
            <para>Important warnings will appear like this.</para>
          </warning>
        </listitem>


      </itemizedlist>
    </section>
    ''')

    def __init__(self, project, defaults):
        DocBookGenerator.__init__(self, project, defaults)
        self.command_gen = NetAppCommandsGenerator(project, defaults)
    
    def build_chapters(self, ns={}):
        book_content = ''
        book_content += self.build_introduction(ns)
        book_content += self.build_design_chapter(ns)

        return book_content

    def build_appendices(self, ns={}):
        """
        Return some appendix information
        """
        content = self.build_activation_section(ns)
        #content += self.build_document_control(ns)
        return content

    def build_introduction(self, ns={}):

        assumptions = []
        #assumptions.append('''Storage will only be provisioned for Oracle 10g databases residing on database hosts.''')

        assumption_list = ''.join( [ '<listitem><para>%s</para></listitem>' % x for x in assumptions ] )

        ns['assumption_list'] = assumption_list
        ns['assumptions'] = self.assumptions.safe_substitute(ns)

        background_text = ''.join([x.get_docbook() for x in self.project.get_backgrounds()])

        ns['background_text'] = background_text

        ns['scope'] = self.build_scope(ns)
        ns['how_to_use'] = self.how_to_use.safe_substitute(ns)
        ns['typographical_conventions'] = self.typographical_conventions.safe_substitute(ns)
        introduction = self.introduction.safe_substitute(ns)

        return introduction

    def build_scope(self, ns):
        ns['scope_list'] = self.build_scope_list(ns)
        return self.scope.safe_substitute(ns)

    def build_scope_list(self, ns):
        """
        Create additional scope list items based on the project configuration.
        """
        scope_list = []
        scope_list.append('''Configuration of NFS exports and mounts.''')

        retstr = ''.join([ '<listitem><para>%s</para></listitem>' % x for x in scope_list ])

        return retstr

    def build_design_chapter(self, ns):
        """
        The design chapter is where the bulk of the design goes.
        """
        chapter = Template('''
  <chapter>
    <title>Storage Design and Configuration</title>
    $topology_section
    $resource_sharing_section
    $operational_maintenance_section
    $connectivity_section
    $vfiler_section
    $project_hosts_section
    $volume_section
    $nfs_config_section
    $iscsi_config_section
    $cifs_config_section
    $snapvault_config_section
    $snapmirror_config_section
  </chapter>
''')

        ns['project_hosts_section'] = self.build_project_hosts_section(ns)
        ns['topology_section'] = self.build_topology_section(ns)
        ns['resource_sharing_section'] = self.build_resource_sharing_section(ns)
        ns['operational_maintenance_section'] = self.build_operational_maintenance_section(ns)
        ns['connectivity_section'] = self.build_connectivity_section(ns)
        ns['vfiler_section'] = self.build_vfiler_section(ns)
        ns['volume_section'] = self.build_volume_section(ns)
        ns['nfs_config_section'] = self.build_nfs_config_section(ns)
        ns['iscsi_config_section'] = self.build_iscsi_config_section(ns)
        ns['cifs_config_section'] = self.build_cifs_config_section(ns)
        ns['snapvault_config_section'] = self.build_snapvault_config_section(ns)
        ns['snapmirror_config_section'] = self.build_snapmirror_config_section(ns)
        
        return chapter.safe_substitute(ns)

    def build_project_hosts_section(self, ns):
        """
        Build the project hosts listing section
        """
        section = Template('''
        <section>
          <title>Project Hosts For Storage Connectivity</title>
          <para>The following hosts will require access to the storage:</para>
          <para>
          $hosts_table
          </para>
        </section>
 ''')

        hosttable = Template('''
        <table tabstyle="techtable-01">
          <title>List of project hosts</title>
            <tgroup cols="4">
              <colspec colnum="1" align="center" colwidth="1*"/>
              <colspec colnum="2" align="center" colwidth="1.5*"/>
              <colspec colnum="3" align="center" colwidth="1.5*"/>
              <colspec colnum="4" align="center" colwidth="1.5*"/>

              <thead>
                <row valign="middle">
                  <entry>
                    <para>Hostname</para>
                  </entry>
                  <entry>
                    <para>Operating System</para>
                  </entry>
                  <entry>
                    <para>Location</para>
                  </entry>
                  <entry>
                    <para>Storage IP Address</para>
                  </entry>
                </row>
              </thead>
              <tbody>
                $hosttable_rows
              </tbody>
          </tgroup>
        </table>
''')

        rowlist = []

        # Sort the list of hosts by site, then ipaddress
        hostlist = [ (host.location, host.get_storage_ips(), host) for host in self.project.get_hosts() ]
        hostlist.sort()

        for location, storage_ips, host in hostlist:

            iplist = ''.join([ '<para>%s</para>' % ipaddr.ip for ipaddr in storage_ips ])
            
            row = '''
            <row>
              <entry>%s</entry>
              <entry>%s %s</entry>
              <entry>%s</entry>
              <entry>%s</entry>
            </row>
            ''' % ( host.name,
                    host.platform,
                    host.operatingsystem,
                    host.location,
                    iplist,
                    )
            rowlist.append( row )
            pass

        # Now that we've built the rowlist, join them together as a string
        tablerows = '\n'.join(rowlist)
        table = hosttable.safe_substitute(hosttable_rows=tablerows)

        return section.safe_substitute(hosts_table=table)

    def build_topology_section(self, ns):
        """
        Build the section describing the project's Topology and Storage Model.
        """
        section = Template('''
        <section>
          <title>Topology and Storage Model</title>
          <para>The fundamental design of the storage solution is described by the following statements:</para>
          <para>
            <itemizedlist>
              <listitem>
                <para><emphasis role="bold">Project IP-SAN Storage VLANs</emphasis> - One storage
                VLAN will be provided to deliver the storage to the &project.title; environment.
                </para>
              </listitem>

              $services_vlan_item

              <listitem>
                <para><emphasis role="bold">NetApp vFilers</emphasis> - One NetApp
                 vFiler will be configured for the project.
                </para>
              </listitem>
              
              <listitem>
                <para><emphasis role="bold">Link Resilience</emphasis> - Each host will be
                dual connected to the IP-SAN.
                </para>
              </listitem>

              <listitem>
                <para><emphasis role="bold">Filer Resilience</emphasis> - Filer failover will be
                configured.
                </para>
              </listitem>

              <listitem>
                <para><emphasis role="bold">Switch Resilience</emphasis> - The edge and core
                switches are provided in pairs for resilience.
                </para>
              </listitem>

              <listitem>
                <para><emphasis role="bold">NearStore</emphasis> - A NearStore device will be
                configured to provide secondary copies of primary data.
                </para>
              </listitem>

              $oracle_database_item

            </itemizedlist>
          </para>
          </section>
 ''')

        if len(self.project.get_services_vlans()) > 0:
            services_vlan = '''
              <listitem>
                <para><emphasis role="bold">Project IP-SAN Services VLANs</emphasis> - Services
                VLANs will be provided to deliver services to the project.
                </para>
              </listitem>
              '''
        else:
            services_vlan = ''

        retstr = section.safe_substitute(services_vlan_item=services_vlan, oracle_database_item='')
        return retstr


    def build_resource_sharing_section(self, ns):
        """
        Build the section describing the project's Topology and Storage Model.
        """
        section = Template('''
          <section>
            <title>Resource Sharing</title>
            <para>The following components of the design may be shared with other projects:
            </para>

            <itemizedlist>
              <listitem>
                <para>The physical NetApp Filer heads and their associated supporting infrastructure
                (FCAL loops, network interfaces, CPU, memory, etc.).
                </para>
              </listitem>

              <listitem>
                <para>The IP-SAN storage network infrastructure.
                </para>
              </listitem>

              <listitem>
                <para>Spare disks will be automatically shared between projects if failures occur.
                </para>
              </listitem>

              <listitem>
                <para>For Data ONTAP 7 implementations, aggregates will be shared with other projects
                according to capacity requirements.
                </para>
              </listitem>

            </itemizedlist>

            <para>The following components of the design are <emphasis role="bold">not</emphasis>
            shared with other projects:
            </para>

            <itemizedlist>
              <listitem>
                <para>The Cat6 edge links between the IP-SAN edge and the hosts.
                </para>
              </listitem>

              <listitem>
                <para>The filer volumes are dedicated to an individual project. This means snapshots will be
                contained within a project.
                </para>
              </listitem>

            </itemizedlist>

          </section>
 ''')
        retstr = section.safe_substitute()
        return retstr
    
    def build_operational_maintenance_section(self, ns):
        """
        Build the section informing the reader of the operational maintenance schedule.
        """
        section = Template('''
          <section>
            <title>Operational Maintenance</title>
            <para>A regularly scheduled maintenance window exists for the environment, from 09:00 - 17:00 every Saturday.
            </para>

            <para>Scheduled maintenance tasks are those that are well understood, well tested and have a very
            low risk of outage. They are used to keep the environment operating efficiently and effectively.
            </para>
    
            <para>As a condition of having storage provided, the project
            accepts that this maintenance window will be used to perform regular, scheduled,
            non-interruptive maintenance, including, but not limited to:

            <itemizedlist>
              <listitem>
                <para>Installation of network switch operating system upgrades in a non-interruptive fashion.
                </para>
              </listitem>

              <listitem>
                <para>Installation of storage device operating system upgrades in a non-interruptive fashion.
                </para>
              </listitem>

              <listitem>
                <para>Periodic testing of automated failover mechanisms, to ensure that such mechanisms
                are correctly configured and will function correctly in an emergency.
                </para>
              </listitem>
            </itemizedlist>
            </para>
            
          </section>
 ''')
        retstr = section.safe_substitute()
        return retstr
    
    def build_connectivity_section(self, ns):
        """
        This section describes how the connectivity to the IP-SAN works.
        """
        section = Template('''
        <section>
          <title>IP-SAN Connectivity</title>
          <para>The IP-SAN configuration designs for this project are provided in the project's IP-SAN
          design document. It contains the IP addressing for each host and the port connectivity
          requirements.
          </para>
          <para>The host-based configurations are outlined in the appropriate host activation guides. From
          these documents some important information is summarised:
          </para>


          <itemizedlist>
            <listitem>
              <para>The host must be within 75m of an IP-SAN edge switch.
              </para>
            </listitem>

            <listitem>
              <para>The host requires two independent Gigabit connections to the IP-SAN.
              </para>
            </listitem>

            <listitem>
              <para>Two cables are required for each host from the host to the nominated pair of IP-SAN
              edge switches. These cables must be Cat6 UTP.
              </para>
            </listitem>

            <listitem>
              <para>The host connections to the IP-SAN should support Jumbo Frames of 9000 bytes.
              </para>
            </listitem>

          </itemizedlist>

          <section>
            <title>Exceptions</title>
            <para>The following exceptions exist for the storage design and implementation for &project.title;:
            </para>

          <itemizedlist>
            <listitem>
              <para>Stress and volume testing (SVT) has not been provisioned and will not be allowed.
              </para>
            </listitem>

            <listitem>
              <para>All resolutions will be IP address based. No DNS or WINS are to be configured on the
              windows hosts. Filer hostname resolution must be added to each host's resolution
              file. For Solaris, Linux and ESX servers, this is <filename>/etc/hosts</filename>. For
              Windows, this is <filename>C:\windows\system32\drivers\etc\hosts</filename> and
              <filename>C:\windows\system32\drivers\etc\lmhosts</filename>
              </para>
            </listitem>
          </itemizedlist>

<screen>&primary.storage_ip;  &vfiler.name;
</screen>
            
          </section>

          
        </section>
          ''')


        return section.safe_substitute()

    def build_vfiler_section(self, ns):
        """
        The vFiler design section.
        """

        section = Template('''
          <section id="vfiler-design">
          <title>vFiler Design</title>
            <para>The following tables provide the vFiler device configuration information.</para>

            $vfiler_section

            $vfiler_routes_section

          </section>
            ''')

        vfiler_section_template = Template('''
          <section>
          <title>$sitetype Site Filer Configuration</title>

          $vfiler_configuration_tables

          </section>
        ''')

        vfiler_configuration_template = Template('''
            <table tabstyle="techtable-01">
              <title>$filername Filer Configuration Information</title>
              <tgroup cols="3">
                <colspec colnum="1" align="left" colwidth="1*"/>
                <colspec colnum="2" align="left" colwidth="1*"/>
                <colspec colnum="3" align="left" colwidth="2*"/>
                <thead>
                  <row>
                    <entry><para>Attribute</para></entry>
                    <entry><para>Value</para></entry>
                    <entry><para>Comment</para></entry>
                  </row>
                </thead>
                <tbody>
                  $rows
                </tbody>
              </tgroup>
            </table>
        ''')

        vfiler_config_row_template = Template('''
                    <entry><para>$attrib</para></entry>
                    <entry><para>$value</para></entry>
                    <entry><para>$comment</para></entry>
        ''')

        services_vlans_config_template = Template('''
            <table tabstyle="techtable-01">
              <title>$filername Service VLANs</title>
              <tgroup cols="5">
                <colspec colnum="1" align="left" colwidth="1*"/>
                <colspec colnum="2" align="left" colwidth="1*"/>
                <colspec colnum="3" align="left" colwidth="1*"/>
                <colspec colnum="4" align="left" colwidth="1*"/>
                <colspec colnum="5" align="left" colwidth="1*"/>                
                <thead>
                  <row>
                    <entry><para>VLAN</para></entry>
                    <entry><para>Interface</para></entry>
                    <entry><para>IP Address</para></entry>
                    <entry><para>Netmask</para></entry>
                    <entry><para>Gateway</para></entry>
                  </row>
                </thead>
                <tbody>
                  $rows
                </tbody>
              </tgroup>
            </table>
        ''')

        # Add a section for each vFiler defined on a primary filer
        log.debug("Building vFiler section...")
        sites = [ (site.type, site) for site in self.project.get_sites() ]
        sites.sort()

        vfiler_sections = []
        for sitetype, site in sites:

            filer_ns = {}
            filer_ns['sitetype'] = sitetype.capitalize()
            
            vfiler_config_tables = []
            log.debug("Filers found: %s", site.get_filers())

            # sort by filer name
            filerlist = [ (filer.name, filer) for filer in site.get_filers() ]
            filerlist.sort()
            for ignored, filer in filerlist:
                #for filer in [ filer for filer in site.filers.values() if filer.type == 'primary' ]:
                for vfiler in filer.get_vfilers():
                    vfiler_attributes = []
                    log.debug("Adding a vFiler: %s", vfiler)
                    template_ns = {}
                    template_ns['sitetype'] = site.type.capitalize()
                    template_ns['filername'] = filer.name
                    template_ns['vfiler_name'] = vfiler.name
                    
                    vfiler_attributes.append( ('vFiler Name', vfiler.name, '') )
                    vfiler_attributes.append( ('Filer Name', filer.name, '') )
                    if filer.cluster_partner is not None:
                        vfiler_attributes.append( ('Filer Partner', filer.cluster_partner.name, '') )
                        pass

                    # Add storage interfaces and IPs
                    vfiler_attributes.append( ('Primary Storage Interface', 'svif0-%s' % vfiler.vlan.number, '') )
                    vfiler_attributes.append( ('Primary Storage IP', vfiler.get_primary_ipaddr().ip, '') )
                    for ipaddr in vfiler.get_alias_ipaddrs():
                        vfiler_attributes.append( ('Alias Storage IP', ipaddr.ip, '') )
                        pass

                    # Add IP space information
                    vfiler_attributes.append( ('IP Space Name', '&ipspace.name;', '') )

                    mtu = vfiler.vlan.mtu
                    if mtu == 9128:
                        mtu = 9000
                    vfiler_attributes.append( ('MTU', '%s' % mtu, '') )

                    vfiler_attributes.append( ('Storage Protocols', self.storage_protocol_cell(), '') )

                    rows = []
                    for attribname, attribval, attribcomment in vfiler_attributes:
                        rows.append("""<row><entry><para>%s</para></entry>
                        <entry><para>%s</para></entry>
                        <entry><para>%s</para></entry></row>
                        """ % (attribname, attribval, attribcomment) )
                        pass

                    template_ns['rows'] = '\n'.join(rows)

                    vfiler_config_tables.append( vfiler_configuration_template.safe_substitute( template_ns ))

                    # Add services VLAN information
                    services_rows = []
                    for ipaddr in vfiler.get_service_ips():
                        for network in ipaddr.vlan.networks:
                            entries = "<entry><para>%s</para></entry>\n" % ipaddr.vlan.number
                            entries += "<entry><para>svif0-%s</para></entry>\n" % ipaddr.vlan.number
                            entries += "<entry><para>%s</para></entry>\n" % ipaddr.ip
                            entries += "<entry><para>%s</para></entry>\n" % network.netmask
                            entries += "<entry><para>%s</para></entry>\n" % network.gateway
                            row = "<row>%s</row>" % entries
                            services_rows.append(row)
                            pass
                        pass

                    services_ns = {}
                    services_ns['filername'] = filer.name
                    services_ns['rows'] = '\n'.join(services_rows)

                    if len(services_rows) > 0:
                        vfiler_config_tables.append( services_vlans_config_template.safe_substitute(services_ns) )
                        pass
                    pass
                pass
        
            filer_ns['vfiler_configuration_tables'] = '\n'.join(vfiler_config_tables)
            vfiler_sections.append( vfiler_section_template.safe_substitute(filer_ns) )
            pass

        ns['vfiler_section'] = '\n'.join( vfiler_sections )
        #ns['primary_site_vfiler_section'] = primary_section.safe_substitute(ns)
        #ns['primary_vfiler_interface_section'] = primary_interface_section.safe_substitute(ns)

##         if self.project.has_dr:
##             ns['dr_site_vfiler_section'] = dr_section.safe_substitute(ns)
##             ns['dr_vfiler_interface_section'] = dr_interface_section.safe_substitute(ns)
##         else:
##             ns['dr_site_vfiler_section'] = ''
##             ns['dr_vfiler_interface_section'] = ''
##             pass

        # Services VLAN routes
        if len(self.project.get_services_vlans()) > 0:
##             ns['services_vlan_routes'] = self.build_services_vlan_routes()
##             ns['vfiler_routes_section'] = vfiler_routes.safe_substitute(ns)
            ns['vfiler_routes_section'] = ''
        else:
            ns['vfiler_routes_section'] = ''
        
        return section.safe_substitute(ns)

    def get_services_rows(self, ns, type='primary'):
        # add services vlans
        services_rows = []
        log.debug("finding services vlans...")
        for vlan in self.project.get_services_vlans(type):
            log.debug("Adding a services VLAN: %s", vlan)
            services_rows.append("""
                  <row>
                    <entry><para>Services VLAN</para></entry>
                    <entry><para>%s</para></entry>
                    <entry><para>%s</para></entry>
                  </row>
                  """ % (vlan.number, vlan.description ) )
            pass
        return ''.join(services_rows)

    def build_services_vlan_routes(self, vfiler):
        """
        Fetch the services vlan additions that we need.
        """
        retstr = "<screen># For Services VLAN access\n"
        retstr += '\n'.join(self.command_gen.services_vlan_route_commands() )
        retstr += '</screen>'

        return retstr
    
    def storage_protocol_cell(self):
        """
        Build the <para/> entries for the storage protocols cell
        """
        paras = []
        for proto in self.project.get_allowed_protocols():
            paras.append('<para>%s</para>' % proto)

        return '\n'.join(paras)

    def build_volume_section(self, ns):
        """
        Build the volume design section
        """

        section = Template("""
        <section>
          <title>Filer Volume Design</title>
          <para>The NAS devices represent groups of storage as volumes. Usable
          space on a volume is the amount available after partitioning and
          space reservation for snapshots used to provide backups. From
          the total volume capacity, 20% will be allocated as the snapshot
          reserve.</para>

          $filer_volume_allocations

          $volume_config_subsection

          $qtree_config_subsection

        </section>
        """)

        volume_allocation_template = Template("""
          <section>
            <title>$filer_name Volume Allocation</title>

            $volume_allocation_table
""")

        volume_allocation_table_template = Template("""
            <informaltable tabstyle="techtable-01">
              <tgroup cols="6" align="left">
                <colspec colnum="1" colname="c1" align="center" colwidth="0.3*"/>
                <colspec colnum="2" colname="c2" align="center" colwidth="1.5*"/>
                <colspec colnum="3" colname="c3" align="center" colwidth="0.5*"/>
                <colspec colnum="4" colname="c4" colwidth="0.3*"/>
                <colspec colnum="5" colname="c5" colwidth="0.3*"/>
                <colspec colnum="6" colname="c6" colwidth="0.3*"/>
                <thead>
                  <row valign="middle">
                    <entry><para>Aggregate</para></entry>
                    <entry><para>Volume</para></entry>
                    <entry><para>Type</para></entry>
                    <entry><para>Snap Reserve (%)</para></entry>
                    <entry><para>Raw Storage (GiB)</para></entry>
                    <entry><para>Usable Storage (GiB)</para></entry>
                  </row>
                </thead>

                <tfoot>
                  $volume_totals
                </tfoot>

                <tbody>
                  $volume_rows
                </tbody>
              </tgroup>
            </informaltable>
          </section>
          """)

        # FIXME:
        # Create a separate table for each Filer, in case we have
        # projects that span multiple Filers/NearStores.
        
        vol_allocations = []
        
        for site in self.project.get_sites():
            # Find all volumes on Filers first, then NearStores
            for filer in site.get_filers():
                tblns = {}
                tblns['sitetype'] = site.type.capitalize()
                tblns['filer_name'] = filer.name
                if filer.type == 'filer':
                    tblns['filer_type'] = 'Filer'
                elif filer.type == 'nearstore':
                    tblns['filer_type'] = 'NearStore'
                    pass

                vol_list = filer.get_volumes()
                if len(vol_list) > 0:
                    # Take the list of volumes and build a list of body rows
                    tblns['volume_rows'] = self.build_vol_rows(vol_list)

                    # calculate primary volume totals
                    total_usable, total_raw = self.get_volume_totals(vol_list)

                    tblns['volume_totals'] = """
                      <row>
                        <entry namest="c1" nameend="c4" align="right"><para>Total:</para></entry>
                        <entry><para>%.1f</para></entry>
                        <entry><para>%.1f</para></entry>
                      </row>""" % (total_raw, total_usable)

                    tblns['volume_allocation_table'] = volume_allocation_table_template.safe_substitute(tblns)
                    vol_allocations.append( volume_allocation_template.safe_substitute(tblns) )
                    pass
                pass
            pass
        ns['filer_volume_allocations'] = '\n'.join( vol_allocations )
        
        # Then do the configuration subsections
        ns['volume_config_subsection'] = self.build_volume_config_section(ns)
        ns['qtree_config_subsection'] = self.build_qtree_config_section(ns)

        return section.safe_substitute(ns)

    def build_vol_rows(self, vol_list):
        """
        Take a list of Volumes and build a list of <row/>s to be inserted
        into a table body.
        """
        volume_rows = []
        for vol in vol_list:
            entries = ''
            entries += "<entry><para>%s</para></entry>" % vol.parent.name
            for attr in [ 'name', 'type' ]:
                entries += "<entry><para>%s</para></entry>" % getattr(vol, attr)
                pass

            # Round raw and usable values to 1 decimal place.
            for attr in [ 'snapreserve', 'raw', 'usable']:
                entries += "<entry><para>%.1f</para></entry>" % getattr(vol, attr)
                
            volume_rows.append("<row>%s</row>" % entries)
            pass
        return '\n'.join(volume_rows)

    def get_volume_totals(self, vol_list):
        """
        Calculate the raw and usable totals for a list of volumes
        """
        usable_total = sum( [ vol.usable for vol in vol_list ])
        raw_total = sum( [ vol.raw for vol in vol_list ])
        return usable_total, raw_total

    def build_vol_totals(self, total_usable, total_raw):
        pass

    def build_volume_config_section(self, ns):
        """
        The volume configuration section defines the volume options for each volume.
        """
        
        filer_volume_config = Template("""
          <section>
            <title>$filer_name Volume Configuration</title>
            <para>The following table details the volume configuration options
            used for the volumes on $filer_name.</para>

            <table tabstyle="techtable-01">
              <title>Volume Configuration for $filer_name</title>
              <tgroup cols="3" align="left">
                <colspec colnum="1" colwidth="2*"/>
                <colspec colnum="2" colwidth="0.75*"/>
                <colspec colnum="3" colwidth="1*"/>                
                  <thead>
                    <row valign="middle">
                      <entry><para>Volume</para></entry>
                      <entry><para>Space Guarantee</para></entry>
                      <entry><para>Options</para></entry>
                    </row>
                  </thead>

                  <tbody>
                    $config_rows
                  </tbody>
                </tgroup>
              </table>
            </section>
            """)

        volume_configs = ''

        for site in self.project.get_sites():
            for filer in site.get_filers():
                config_ns = {}
                config_ns['filer_name'] = filer.name
                config_rows = self.get_volume_options_rows(filer)
                if len(config_rows) > 0:
                    config_ns['config_rows'] = config_rows
                    volume_configs += filer_volume_config.safe_substitute(config_ns)
                    pass
                pass
            pass
            
        return volume_configs

    def get_volume_options_rows(self, filer):
        """
        Build the volume options rows for the previously defined volumes
        for a given site/filer.
        """
        rows = []
        for volume in filer.get_volumes():
            row_detail = "<entry><para>%s</para></entry>\n" % volume.name
            row_detail += "<entry><para>%s</para></entry>\n" % volume.space_guarantee
            option_str = ''
            for key,value in volume.get_options().items():
                option_str += "<para>%s=%s</para>" % (key, value)
                #option_str = ''.join([ "<para>%s</para>" % x for x in volume.options ])
                pass
            
            # Add autosize options
            if volume.autosize:
                option_str += "<para>autosize_max=%s</para>" % volume.autosize.max
                option_str += "<para>autosize_increment=%s</para>" % volume.autosize.increment
            
            # Add autodelete options
            if volume.autodelete:
                settings = volume.autodelete.get_settings()
                for key in settings:
                    option_str += "<para>autodelete %s=%s</para>" % (key, settings[key])
            
            row_detail += "<entry>%s</entry>\n" % option_str

            # comment column. No longer used.
            #row_detail += "<entry/>\n"

            row = "<row valign='middle'>%s</row>" % row_detail

            rows.append(row)

        return '\n'.join(rows)

    def get_volume_options_entry(self, ns, volume_name):
        """
        Build the volume options entry based on the volume's options.
        """
        options = self.project.get_volume_options(volume_name)

    def build_qtree_config_section(self, ns):
        """
        Qtree layout and definitions.
        """
        section = Template("""
        <section>
          <title>Volume Qtree Structure</title>

        <para>Qtrees on primary site NearStores will be created automatically
	as part of &snapvault; replication; this will produce the
	same qtree structure on NearStores as exists on the source volumes.
        </para>

        <para>Qtrees on secondary site Filers and NearStores will be created automatically
	as part of the SnapMirror replication; this will produce the
	same qtree structure as exists on the source volumes.
        </para>

          $filer_qtrees

        </section>
        """)

        qtrees_table_template = Template("""
        <table tabstyle="techtable-01">
          <title>Qtree Configuration For $filer_name</title>
          <tgroup cols="4" align="left">
            <colspec colname="c1" colwidth="2*"/>
            <colspec colname="c2" align="center" colwidth="1*"/>
            <colspec colname="c2" align="center" colwidth="0.5*"/>
            <colspec colname="c3" colwidth="1.5*"/>
            <thead>
              <row valign="middle">
                <entry align="center"><para>Qtree Name</para></entry>
                <entry><para>Quota Details</para></entry>
                <entry><para>Qtree Security Style</para></entry>
                <entry><para>Comments</para></entry>
              </row>
            </thead>

            <tbody>
              $qtree_rows
            </tbody>
          </tgroup>
        </table>

      """)


        qtree_tables = []
        for site in self.project.get_sites():
            for filer in [ x for x in site.get_filers() if x.type == 'filer' ]:
                log.debug("finding qtrees for filer: %s", filer.name)
                tblns = {}
                tblns['filer_name'] = filer.name
                filer_qtree_rows = self.get_filer_qtree_rows(filer)
                tblns['qtree_rows'] = filer_qtree_rows
                if len(filer_qtree_rows) > 0:
                    log.debug("Adding qtree table for filer %s", filer.name)
                    qtree_tables.append( qtrees_table_template.safe_substitute(tblns) )
                    pass
                pass
            pass
        pass


        ns['filer_qtrees'] = '\n'.join(qtree_tables)
        return section.safe_substitute(ns)

    def get_filer_qtree_rows(self, filer):
        """
        Process the filer's qtrees in the format required for the qtree
        configuration table.
        """
        rows = []
        qtree_list = []
        for vol in [ vol for vol in filer.get_volumes() if vol.type not in ['snapvaultdst', 'snapmirrordst'] ]:
            log.debug("finding qtrees on volume: %s: %s", vol, vol.get_qtrees())
            qtree_list.extend(vol.get_qtrees())

        for qtree in qtree_list:
            row = """
            <row valign='middle'>
            <entry><para>/vol/%s/%s</para></entry>
            <entry><para>Reporting Only</para></entry>
            <entry><para>%s</para></entry>
            <entry><para>%s</para></entry>
            </row>
            """ % ( qtree.volume.name, qtree.name, qtree.security, qtree.comment )
            rows.append(row)
            pass
        return '\n'.join(rows)

    def build_nfs_config_section(self, ns):

        section = Template("""
        <section>
          <title>NFS Storage Configuration</title>
          <para>This section provides the NFS configuration for &project.title;.</para>

          <section>
            <title>Default NFS Mount Options</title>

            <para>All Linux hosts must use the following mount options when mounting NFS storage:</para>
            <screen>bg,hard,tcp,vers=3,rsize=65536,wsize=65536,timeo=600</screen>

            <para>All Solaris hosts must use the following mount options when mounting NFS storage:</para>
            <screen>bg,hard,proto=tcp,vers=3,rsize=65536,wsize=65536</screen>

            <para>Mount options for ESX NFS datastores will be handled and managed by the ESX server storage configuration subsystem.</para>
          </section>

          <section>
            <title>Host NFS Configuration</title>
            <para>The following tables provide the qtree NFS exports and host mount configurations.</para>

            $nfs_exports_tables

            <note>
            <para>Refer to the specific operating system host activation guides for further information on host
            side NFS activation.</para>
            </note>

          </section>

        </section>

            """)
            
        nfs_table_template = Template("""<para>
            <table tabstyle="techtable-01">
              <title>NFS Exports for $sitetype Site</title>
              <tgroup cols="3">
                <colspec colnum="1" align="left" colwidth="2*"/>
                <colspec colnum="2" align="center" colwidth="0.75*"/>
                <colspec colnum="3" align="left" colwidth="1*"/>

                <thead>
                  <row valign="middle">
                    <entry><para>Mount Path</para></entry>
                    <entry><para>Host</para></entry>
                    <entry><para>Additional Mount Options</para></entry>
                  </row>
                </thead>

                <tbody>
                  $nfs_qtree_rows
                </tbody>
              </tgroup>
            </table>
            </para>
        """)

        nfs_tables = []
        for sitetype in ['primary', 'secondary']:
            tblns = {}
            # Only include the NFS qtree section if there are NFS qtrees
            nfs_qtree_rows = '\n'.join(self.get_nfs_qtree_rows(ns, sitetype))
            if len(nfs_qtree_rows) > 0:
                #log.debug("Found NFS qtrees: '%s'", nfs_qtree_rows)
                tblns['sitetype'] = sitetype.capitalize()
                tblns['nfs_qtree_rows'] = nfs_qtree_rows
                nfs_tables.append( nfs_table_template.safe_substitute(tblns))
                pass
            pass

        if len(nfs_tables) > 0:
            ns['nfs_exports_tables'] = '\n'.join(nfs_tables)
            return section.safe_substitute(ns)
        else:
            return ''

    def get_nfs_qtree_rows(self, ns, site):
        """
        Get the qtree level NFS configuration information for a site.
        @returns rows: an XML string of the rows data.
        """
        # FIXME: Group this by host after building the rows, and make the left
        # column the host.
        rows = []

        # only create export definition for nfs volumes on primary filers
        qtree_list = []
        # select only volumes on filers of type 'filer'
        volumes = [ x for x in self.project.get_volumes() if x.get_filer().type in ['filer'] and x.protocol == 'nfs' ]
        for vol in volumes:
            # only worry about NFS qtrees
            qtree_list.extend(vol.get_qtrees())
            pass
        
        #qtree_list = [ x for x in self.project.get_site_qtrees(ns, site) if x.volume.proto == 'nfs' and x.volume.type not in [ 'snapvaultdst', 'snapmirrordst' ] ]
        for qtree in qtree_list:
            #log.debug("Adding NFS export definition for %s", qtree)
            # For each qtree, add a row for each host that needs to mount it

            # Read/Write mounts
            for export in qtree.get_rw_exports():
                filerip = export.fromip

                #filerip = qtree.volume.volnode.xpath("ancestor::vfiler/primaryip/ipaddr")[0].text
                mountopts = self.project.get_host_qtree_mountoptions(export.tohost, qtree)
                mountoptions = ''.join([ '<para>%s</para>' % x for x in mountopts ])

                # Optional IP address that should be used on the host to mount the storage
                # Only have this in the document if a toip is defined.
                if export.toip is not None:
                    toip_string = "<para>%s</para>" % export.toip
                else:
                    toip_string = ""
                    
                entries = """
                    <entry><para>%s:/vol/%s/%s</para></entry>
                    <entry><para>%s</para>%s</entry>
                    <entry>%s</entry>
                    """ % ( filerip, qtree.volume.name, qtree.name, export.tohost.name, toip_string, mountoptions )
                row = "<row valign='middle'>%s</row>" % entries
                rows.append(row)
                pass

            # Read Only mounts
            for export in qtree.get_ro_exports():
                filerip = export.fromip

                #filerip = qtree.volume.volnode.xpath("ancestor::vfiler/primaryip/ipaddr")[0].text
                mountopts = self.project.get_host_qtree_mountoptions(export.tohost, qtree)
                mountoptions = ''.join([ '<para>%s</para>' % x for x in mountopts ])

                # Optional IP address that should be used on the host to mount the storage
                # Only have this in the document if a toip is defined.
                if export.toip is not None:
                    toip_string = "<para>%s</para>" % export.toip
                else:
                    toip_string = ""
                    
                entries = """
                    <entry><para>%s:/vol/%s/%s</para></entry>
                    <entry><para>%s</para>%s</entry>
                    <entry>%s</entry>
                    """ % ( filerip, qtree.volume.name, qtree.name, export.tohost.name, toip_string, mountoptions )
                row = "<row valign='middle'>%s</row>" % entries
                rows.append(row)
                log.debug("Added ro host/qtree: %s/%s", export.tohost.name, qtree.name)
                pass

            pass
        return rows

    def build_iscsi_config_section(self, ns):
        """
        iSCSI configuration section
        """
        section = Template("""
        <section>
          <title>iSCSI Storage Configuration</title>
          <para>This section provides the iSCSI configuration for &project.title;.</para>

          <section>
            <title>Initiator and CHAP Configuration</title>

            <table tabstyle="techtable-01">
              <title>Project Global iSCSI CHAP Configuration for &project.title;</title>
              <tgroup cols="2">
                <colspec colnum="1" align="center" colwidth="2*"/>
                <colspec colnum="2" align="center" colwidth="2*"/>

                <thead>
                  <row valign="middle">
                    <entry><para>CHAP Username</para></entry>
                    <entry><para>CHAP Password</para></entry>
                  </row>
                </thead>

                <tbody>
                  <row valign="middle">
                    <entry><para>$iscsi_chap_username</para></entry>
                    <entry><para>$iscsi_chap_password</para></entry>
                  </row>
                </tbody>
              </tgroup>
            </table>

            <note>
              <para>Ensure that the default iSCSI security mode on all project vFilers is set to CHAP, using the
              following command syntax:</para>
              <screen># vfiler run &vfiler.name; iscsi security default -s CHAP -n $iscsi_chap_username -p $iscsi_chap_password</screen>
            </note>

          </section>

          <section>
            <title>iSCSI iGroup Configuration</title>
            <para>iSCSI initiator names must be obtained from each client host, and should be supplied by the project team.</para>
            
            $igroup_tables

          </section>

          <section>
            <title>iSCSI LUN Configuration</title>
            <para>iSCSI initiator names must be obtained from each client host, and should be supplied by the project team.</para>

            $lun_tables

          </section>

          <para>Once the above iSCSI configuration has been applied on the project's vfiler, the hosts can
          then be configured to connect to the vFiler's iSCSI target subsystem and mount the
          configured iSCSI LUNs.
          </para>

          <note>
            <para>Refer to the specific operating system host activation guides for further information on host
            side iSCSI activation.
            </para>
          </note>

      </section>
      """)

        igroup_table_template = Template("""
            <table tabstyle="techtable-01">
              <title>iSCSI iGroup Configuration on $filer_name</title>
              <tgroup cols="4">
                <colspec colnum="1" align="left" colwidth="1.2*"/>
                <colspec colnum="2" align="left" colwidth="2.5*"/>
                <colspec colnum="3" align="left" colwidth="1*"/>
                <colspec colnum="4" align="left" colwidth="1*"/>
                <thead>
                  <row valign="middle">
                    <entry><para>iGroup</para></entry>
                    <entry><para>Initator Name</para></entry>
                    <entry><para>Type</para></entry>
                    <entry><para>OS Type</para></entry>
                  </row>
                </thead>

                <tbody>
                  $iscsi_igroup_rows
                </tbody>
              </tgroup>
            </table>
            """)
        
        lun_table_template = Template("""
            <table tabstyle="techtable-01">
              <title>iSCSI LUN Configuration on $filer_name</title>
              <tgroup cols="4">
                <colspec colnum="1" align="left" colwidth="3*"/>
                <colspec colnum="2" align="left" colwidth="0.75*"/>
                <colspec colnum="3" align="left" colwidth="0.75*"/>
                <colspec colnum="4" align="left" colwidth="1.2*"/>
                <thead>
                  <row valign="middle">
                    <entry><para>LUN Name</para></entry>
                    <entry><para>Size (GiB)</para></entry>
                    <entry><para>OS Type</para></entry>
                    <entry><para>igroup</para></entry>
                  </row>
                </thead>

                <tbody>
                  $iscsi_lun_rows
                </tbody>
              </tgroup>
            </table>
            """)

        ns['iscsi_chap_username'] = self.project.title
        ns['iscsi_chap_password'] = self.project.get_iscsi_chap_password(ns['iscsi_prefix'])

        if len(self.project.get_luns()) > 0:
            igroup_tables = []
            lun_tables = []

            for filer in [ x for x in self.project.get_filers() if x.type in ['filer', ] ]:
                log.debug("Finding igroups for filer %s...", filer.name)
                tblns = {}
                tblns['filer_name'] = filer.name
                igroup_rows = self.get_iscsi_igroup_rows(filer)
                if len(igroup_rows) > 0:
                    tblns['iscsi_igroup_rows'] = igroup_rows
                    igroup_tables.append(igroup_table_template.safe_substitute(tblns))
                    log.debug("added table for filer: %s", filer.name)
                    pass
                
                lun_rows = self.get_iscsi_lun_rows(filer)
                if len(lun_rows) > 0:
                    tblns['iscsi_lun_rows'] = lun_rows
                    lun_tables.append(lun_table_template.safe_substitute(tblns))
                    pass
                pass

            ns['igroup_tables'] = '\n'.join(igroup_tables)
            ns['lun_tables'] = '\n'.join(lun_tables)

            return section.safe_substitute(ns)
        else:
            return ''

    def get_iscsi_igroup_rows(self, filer):
        """
        Find a list of iSCSI iGroups for the project, and convert
        them into the appropriate rows for the iGroup configuration table.
        """
        rows = []

        igroup_list = filer.get_igroups()

        for igroup in igroup_list:
            entries = "<entry><para>%s</para></entry>\n" % igroup.name
            entries += "<entry><para>%s</para></entry>\n" % ''.join( [ "<para>%s</para>" % export.tohost.iscsi_initiator for export in igroup.get_exports() ] )
            entries += "<entry><para>iSCSI</para></entry>\n"
            entries += "<entry><para>%s</para></entry>\n" % igroup.type            

            rows.append("<row valign='middle'>%s</row>\n" % entries)
        return '\n'.join(rows)

    def get_iscsi_lun_rows(self, filer):
        rows = []
        lunlist = filer.get_luns()
        for lun in lunlist:
            log.debug("lun is: %s", lun)
            entries = "<entry><para>%s</para></entry>\n" % lun.full_path()
            entries += "<entry><para>%.2f</para></entry>\n" % lun.size
            entries += "<entry><para>%s</para></entry>\n" % lun.ostype
            entries += "<entry><para>%s</para></entry>\n" % lun.igroup.name
            
            rows.append("<row valign='middle'>%s</row>\n" % entries)
        return '\n'.join(rows)
        
    def build_cifs_config_section(self, ns):

        section = Template("""
        <section>
          <title>CIFS Storage Configuration</title>
          <para/>

          $cifs_ad_section

          $cifs_shares_section

          $cifs_hosts_config_section
          
        </section>
        """)
        if 'cifs' in self.project.get_allowed_protocols():
            log.debug("Configuring CIFS...")
            ns['cifs_ad_section'] = self.build_cifs_active_directory_section(ns)
            
            ns['cifs_shares_section'] = self.build_cifs_shares_section(ns)

            ns['cifs_hosts_config_section'] = self.build_cifs_hosts_config_section(ns)
            
            return section.safe_substitute(ns)
        else:
            return ''

    def build_cifs_active_directory_section(self, ns):
        """
        Set up any CIFS active directory configuration information
        """
        # FIXME: This is purely static for now, if CIFS is enabled.
        log.debug("Setting up AD authentication for CIFS...")
        section = Template("""
        <section>
          <title>CIFS Active Directory Configuration</title>
          <para>The following table provides the CIFS active directory
          configuration for the &project.title; project.</para>

          $cifs_ad_filer_tables

        </section>
        """)

        table_template = Template("""
        <table tabstyle='techtable-03'>
          <title>Active Directory Configuration for $filer_name:$vfiler_name</title>
            <tgroup cols='2'>
              <colspec colnum="1" align="left" colwidth="1*"/>
              <colspec colnum="2" align="left" colwidth="2*"/>

            <tbody>
              <row valign="middle">
                <entry><para>Filer:</para></entry>
                <entry><para>$filer_name</para></entry>
              </row>

              <row valign="middle">
                <entry><para>vFiler:</para></entry>
                <entry><para>$vfiler_name</para></entry>
              </row>

              <row valign="middle">
                <entry><para>Authentication Type:</para></entry>
                <entry><para>Active Directory</para></entry>
              </row>

              <row valign="middle">
                <entry><para>WINS Servers:</para></entry>
                <entry>$wins_servers</entry>
              </row>

              <row valign="middle">
                <entry><para>DNS Servers:</para></entry>
                <entry>$dns_servers</entry>
              </row>

              <row valign="middle">
                <entry><para>DNS Domain Name:</para></entry>
                <entry><para>$dns_domain_name</para></entry>
              </row>

              <row valign="middle">
                <entry><para>vFiler NetBIOS Name:</para></entry>
                <entry><para>$vfiler_netbios_name</para></entry>
              </row>

              <row valign="middle">
                <entry><para>vFiler NetBIOS Aliases:</para></entry>
                <entry>$vfiler_netbios_aliases</entry>
              </row>

              <row valign="middle">
                <entry><para>Fully Qualified AD Domain Name:</para></entry>
                <entry><para>$ad_domain_name</para></entry>
              </row>

              <row valign="middle">
                <entry><para>vFiler Computer Account Location in AD:</para></entry>
                <entry>$vfiler_ad_account_location</entry>
              </row>

            </tbody>
          </tgroup>
        </table>
        """)

        tables = []

        for filer in [ x for x in self.project.filers.values() if x.type in ['primary', 'nearstore',] ]:
            log.debug("Adding AD config for filer: %s", filer.name)
            for vfiler in filer.vfilers.values():
                tabns = {}
                tabns['filer_name'] = filer.name
                tabns['vfiler_name'] = vfiler.name

                tabns['wins_servers'] = '\n'.join( [ '<para>%s</para>' % x for x in vfiler.winsservers ] )

                tabns['dns_servers'] =  '\n'.join( [ '<para>%s</para>' % x for x in vfiler.nameservers ] )

                tabns['dns_domain_name'] = vfiler.dns_domain_name

                tabns['vfiler_netbios_name'] = vfiler.netbios_name()
                #tabns['vfiler_netbios_aliases'] = "<para>%s</para>" % vfiler.name
                # No NetBIOS aliases will be used by default.
                tabns['vfiler_netbios_aliases'] = "<para>None</para>"
                tabns['ad_domain_name'] = vfiler.fqdn()
                tabns['vfiler_ad_account_location'] = vfiler.ad_account_location
                
                tables.append( table_template.safe_substitute(tabns) )

        ns['cifs_ad_filer_tables'] = '\n'.join(tables)
                
        return section.safe_substitute(ns)

    def build_cifs_shares_section(self, ns):
        """
        Build the CIFS sharing section for the hosts.
        """

        section = Template("""
        <section>
          <title>CIFS Share Configuration</title>
          <para/>

          $cifs_shares_tables
          
        </section>
        """)
        
        cifs_shares_table_template = Template("""
        <table tabstyle='techtable-01'>
          <title>CIFS Share Configuration for $filer_name</title>
          <tgroup cols='3'>
            <colspec colnum="1" align="left" colwidth="1.5*"/>
            <colspec colnum="2" align="left" colwidth="1*"/>
            <colspec colnum="3" align="left" colwidth="1*"/>

            <thead>
              <row valign='middle'>
                <entry><para>Qtree</para></entry>
                <entry><para>Sharename</para></entry>
                <entry><para>Permissions</para></entry>
              </row>
            </thead>

            <tbody>
              $table_rows
            </tbody>
            
          </tgroup>
        </table>
        """)

        tables = []

        for filer in [ x for x in self.project.filers.values() if x.type == 'primary' ]:
            log.debug("Findings cifs qtrees on filer %s", filer.name)
            cifs_qtrees = self.project.get_cifs_qtrees(filer)
            if len(cifs_qtrees) > 0:
                log.debug("Found CIFS exports on filer %s", filer)

                tabns = {}
                tabns['filer_name'] = filer.name

                rows = []
                for qtree in cifs_qtrees:
                    row = []

                    perms = []
                    # FIXME: Read/write or read-only permissions are not
                    # properly supported on CIFS as yet.
                    if len(qtree.rwexports) > 0:
                        perms.append( "<para>Domain Admins rwx</para>" )
                        #perms.extend( [ "<para>CORP\%s &lt;full&gt;</para>" % x.name for x in qtree.rwhostlist ] )
                        pass
                    
                    if len(qtree.roexports) > 0:
                        perms.append( "<para>Domain Admins rwx</para>" )
                        #perms.extend( [ "<para>CORP\%s &lt;read-only&gt;</para>" % x.name for x in qtree.rohostlist ] )
                        pass
                    
                    # only add rows if there are permissions set for them.
                    if len(perms) > 0:

                        row.append("<entry><para>%s</para></entry>" % qtree.full_path() )
                        row.append("<entry><para>%s</para></entry>" % qtree.cifs_share_name() )

                        row.append("<entry>%s</entry>" % ''.join( perms ) )

                        rows.append("<row>%s</row>" % '\n'.join(row) )

                    else:
                        log.warn("Qtree '%s' is defined, but no CIFS hosts have permission to see it.", qtree.full_path())
                    pass

                tabns['table_rows'] = '\n'.join(rows)
                tables.append( cifs_shares_table_template.safe_substitute(tabns) )
                pass
            pass
                
        ns['cifs_shares_tables'] = '\n'.join(tables)
        return section.safe_substitute(ns)

    def build_cifs_hosts_config_section(self, ns):
        """
        Information how to configure CIFS shares on hosts.
        """
        section = Template("""
        <section>
          <title>Host Configurations For CIFS Mounts</title>
          <para>Use the following steps to turn on the 'Client for Microsoft Networks'
          and 'File and Printer Sharing for Microsoft Networks' options for MS Windows
          Hosts.</para>

          <note>
            <para>These steps must be performed on all MS Windows hosts.</para>
          </note>

          <procedure>
            <step>
              <para>Navigate to Control Panel <symbol role="symbolfont">&rarr;</symbol> Network Connections</para>
            </step>

            <step>
              <para>Double click on the teamed storage interface</para>
            </step>

            <step>
              <para>Click the 'Properties' button</para>
            </step>

            <step>
              <para>Tick 'Click for Microsoft Networks' check box.</para>
            </step>

            <step>
              <para>Tick 'File and Printer Sharing for Microsoft Networks' check box.</para>
            </step>

          </procedure>
        </section>
        """)
        return section.safe_substitute(ns)
    
    def build_snapvault_config_section(self, ns):

        section = Template("""
        <section>
          <title>SnapVault Configuration</title>
          <para>The following SnapVault configuration will be configured for &project.title;:
          </para>

            <table tabstyle="techtable-01">
              <title>SnapVault Schedules</title>
              <tgroup cols="5">
                <colspec colnum="1" align="left" colwidth="1*"/>
                <colspec colnum="2" align="left" colwidth="1*"/>
                <colspec colnum="3" align="left" colwidth="1*"/>
                <colspec colnum="4" align="left" colwidth="1*"/>
                <colspec colnum="5" align="left" colwidth="1*"/>
                <thead>
                  <row valign="middle">
                    <entry><para>Source</para></entry>
                    <entry><para>Destination</para></entry>
                    <entry><para>Snapshot Basename</para></entry>
                    <entry><para>Source Schedule
                      <footnote id="netapp.schedule.format">
                        <para>Format is: number@days_of_the_week@hours_of_day</para>
                      </footnote></para></entry>
                    <entry><para>Destination Schedule<footnoteref linkend="netapp.schedule.format"/></para></entry>
                  </row>
                </thead>

                <tbody>
                  $snapvault_rows
                </tbody>
              </tgroup>
            </table>

        </section>
        """)

        snapvault_rows = self.get_snapvault_rows(ns)
        if len(snapvault_rows) > 0:
            ns['snapvault_rows'] = snapvault_rows
            return section.safe_substitute(ns)
        else:
            return ''

    def get_snapvault_rows(self, ns):
        """
        Build a list of snapvault rows based on the snapvault relationships
        defined in the configuration.
        """
        snapvaults = self.project.get_snapvaults()
        rows = []
        for sv in snapvaults:
            entries = ''
            entries += "<entry><para>%s</para></entry>\n" % sv.sourcevol.namepath()
            entries += "<entry><para>%s</para></entry>\n" % sv.targetvol.namepath()
            entries += "<entry><para>%s</para></entry>\n" % sv.basename
            entries += "<entry><para>%s</para></entry>\n" % sv.src_schedule
            entries += "<entry><para>%s</para></entry>\n" % sv.dst_schedule
            row = "<row>%s</row>\n" % entries
            rows.append(row)
            pass

        return ''.join(rows)

    
    def build_snapmirror_config_section(self, ns):

        section = Template("""
        <section>
          <title>SnapMirror Configuration</title>
          <para>The following SnapMirror configuration will be configured for &project.title;:
          </para>

            <table tabstyle="techtable-01">
              <title>SnapMirror Schedules</title>
              <tgroup cols="3">
                <colspec colnum="1" align="left" colwidth="1*"/>
                <colspec colnum="2" align="left" colwidth="1*"/>
                <colspec colnum="3" align="left" colwidth="1*"/>
                <thead>
                  <row valign="middle">
                    <entry><para>Source</para></entry>
                    <entry><para>Destination</para></entry>
                    <entry><para>Schedule<footnote id="netapp.snapmirror.schedule.format">
                        <para>Format is: minute hour dayofmonth dayofweek</para>
                      </footnote></para></entry>
                  </row>
                </thead>

                <tbody>
                  $snapmirror_rows
                </tbody>
              </tgroup>
            </table>

        </section>
        """)

        snapmirror_rows = self.get_snapmirror_rows(ns)
        if len(snapmirror_rows) > 0:
            ns['snapmirror_rows'] = snapmirror_rows
            return section.safe_substitute(ns)
        else:
            return ''

    def get_snapmirror_rows(self, ns):
        """
        Build a list of snapmirror rows based on the snapmirror relationships
        defined in the configuration.
        """
        snapmirrors = self.project.get_snapmirrors()
        rows = []
        for sm in snapmirrors:
            entries = ''
            entries += "<entry><para>%s</para></entry>" % sm.sourcevol.namepath()
            entries += "<entry><para>%s</para></entry>" % sm.targetvol.namepath()
            entries += "<entry><para>%s</para></entry>" % sm.etc_snapmirror_conf_schedule()
            row = "<row>%s</row>" % entries
            rows.append(row)
            pass

        return ''.join(rows)

    def build_activation_section(self, ns):
        log.debug("Adding activation instructions...")

        # Old version with subsections
##         section = Template("""
##         <appendix>
##           <title>Activation Instructions</title>

##           $activation_commands
          
##         </appendix>
##         """)

        # new version where each filer is a separate appendix.
        section = Template("""
          $activation_commands
        """)

        ns['activation_commands'] = self.build_activation_commands(ns)
        return section.safe_substitute(ns)
    
    def build_activation_commands(self, ns):

        activation_commands = ''

        for filer in self.project.get_filers():
            for vfiler in filer.get_vfilers():
                log.debug("Building activation commands for %s:%s", filer, vfiler)
                activation_commands += self.build_filer_activation_commands(filer, vfiler, ns)
                
        # Build the commands for all primary filers
#         for filer in [ x for x in self.project.get_filers() if x.site.type == 'primary' and x.type == 'primary' ]:
#             # FIXME: Only supports one vFiler per Filer.
#             vfiler = filer.get_vfilers()[0]
#             activation_commands += self.build_filer_activation_commands(filer, vfiler, ns)

#         for filer in [ x for x in self.project.get_filers() if x.site.type == 'primary' and x.type == 'secondary' ]:
#             # My vfiler is the vfiler from the primary
#             # FIXME: This is broken and won't work.
#             vfiler = filer.secondary_for.vfilers.values()[0]
#             activation_commands += self.build_filer_activation_commands(filer, vfiler, ns)

#         for filer in [ x for x in self.project.get_filers() if x.site.type == 'primary' and x.type == 'nearstore' ]:
#             vfiler = filer.get_vfilers()[0]
#             activation_commands += self.build_filer_activation_commands(filer, vfiler, ns)

#         # Build the commands for all secondary filers
#         for filer in [ x for x in self.project.get_filers() if x.site.type == 'secondary' and x.type == 'primary' ]:
#             vfiler = filer.get_vfilers()[0]
#             activation_commands += self.build_filer_activation_commands(filer, vfiler, ns)

#         for filer in [ x for x in self.project.get_filers() if x.site.type == 'secondary' and x.type == 'secondary' ]:
#             # My vfiler is the vfiler from the primary
#             vfiler = filer.secondary_for.get_vfilers()[0]
#             activation_commands += self.build_filer_activation_commands(filer, vfiler, ns)

#         for filer in [ x for x in self.project.get_filers() if x.site.type == 'secondary' and x.type == 'nearstore' ]:
#             vfiler = filer.get_vfilers()[0]
#             activation_commands += self.build_filer_activation_commands(filer, vfiler, ns)

        return activation_commands

    def build_filer_activation_commands(self, filer, vfiler, ns):
        """
        Build the various command sections for a specific filer.
        """
        log.debug("Adding activation commands for %s", filer.name)
        cmd_ns = {}
        cmd_ns['commands'] = ''
        
        section = Template("""<appendix>
          <title>Activation commands for %s</title>
          $commands
        </appendix>
        """ % filer.name)

        # Volumes are not created on secondary filers
        if filer.is_active_node:
            cmds = '\n'.join( self.command_gen.filer_vol_create_commands(filer) )
            cmd_ns['commands'] += """<section>
            <title>Volume Creation</title>
            <screen>%s</screen>
            </section>""" % cmds

        #
        # Create qtrees
        #
        cmds = self.command_gen.filer_qtree_create_commands(filer)
        if len(cmds) > 0:
            cmd_ns['commands'] += """<section>
            <title>Qtree Creation</title>
            <screen>%s</screen>
            </section>""" % '\n'.join(cmds)

        # Create the vfiler VLAN
        cmds = '\n'.join( self.command_gen.vlan_create_commands(filer, vfiler) )
        cmd_ns['commands'] += """<section>
        <title>VLAN Creation</title>
        <screen>%s</screen>
        </section>""" % cmds

        # Create the vfiler IPspace
        cmds = '\n'.join( self.command_gen.ipspace_create_commands(filer) )
        cmd_ns['commands'] += """<section>
        <title>IP Space Creation</title>
        <screen>%s</screen>
        </section>""" % cmds

        # Only create the vfiler on primary and nearstore filers
        if filer.is_active_node:
            cmds = '\n'.join( self.command_gen.vfiler_create_commands(filer, vfiler) )
            cmd_ns['commands'] += """<section>
            <title>vFiler Creation</title>
            <screen>%s</screen>
            </section>""" % cmds

        # Don't add volumes on secondary filers
        if filer.is_active_node:
            cmds = '\n'.join( self.command_gen.vfiler_add_volume_commands(filer, vfiler) )
            if len(cmds) > 0:
                cmd_ns['commands'] += """<section>
                <title>vFiler Volume Addition</title>
                <screen>%s</screen>
                </section>""" % cmds

        # Add interfaces
        cmds = '\n'.join( self.command_gen.vfiler_add_storage_interface_commands(filer, vfiler) )
        cmd_ns['commands'] += """<section>
        <title>Interface Configuration</title>
        <screen>%s</screen>
        </section>""" % cmds

        # Configure secureadmin
        if filer.is_active_node:
            cmds = '\n'.join( self.command_gen.vfiler_setup_secureadmin_ssh_commands(vfiler) )
            cmd_ns['commands'] += """<section>
            <title>SecureAdmin Configuration</title>
            <para>Run the following commands to enable secureadmin within the vFiler:</para>
            <screen>%s</screen>
            </section>""" % cmds

        # Inter-project routing
##         cmds = '\n'.join( self.command_gen.vfiler_add_inter_project_routing(vfiler) )
##         cmd_ns['commands'] += """<section>
##         <title>Inter-Project Routing</title>
##         <screen>%s</screen>
##         </section>""" % cmds

        if filer.is_active_node:
            cmds = '\n'.join( self.command_gen.vfiler_set_allowed_protocols_commands(vfiler) )
            cmd_ns['commands'] += """<section>
            <title>Allowed Protocols</title>
            <screen>%s</screen>
            </section>""" % cmds

        # Careful! Quotas file is the verbatim file contents, not a list!
        if filer.is_active_node:
            cmds = '\n'.join( self.command_gen.vfiler_quotas_add_commands(filer, vfiler) )
            cmd_ns['commands'] += """<section>
            <title>Quota File Contents</title>
            <para>Run the following commands to create the quotas file <filename>/vol/%s_root/etc/quotas</filename>:
            </para>
            <screen>%s</screen>
            </section>""" % ( ns['vfiler_name'], cmds )

            # Quota enablement
            cmds = '\n'.join(self.command_gen.vfiler_quotas_enable_commands(filer, vfiler))
            cmd_ns['commands'] += """<section>
            <title>Quota Enablement Commands</title>
            <para>Execute the following commands on the filer to enable quotas:
            </para>
            <screen>%s</screen>
            </section>""" % cmds

        if filer.is_active_node and filer.type == 'filer':
            cmds = '\n'.join( self.command_gen.filer_snapreserve_commands(filer) )
            cmd_ns['commands'] += """<section>
            <title>Snap Reserve Configuration</title>
            <screen>%s</screen>
            </section>""" % cmds

        if filer.is_active_node and filer.type == 'filer':
            cmds = '\n'.join( self.command_gen.filer_snapshot_commands(filer) )
            cmd_ns['commands'] += """<section>
            <title>Snapshot Configuration</title>
            <screen>%s</screen>
            </section>""" % cmds

        # initialise the snapvaults to the nearstore
        if filer.is_active_node and filer.type == 'nearstore':
            cmds = '\n'.join( self.command_gen.filer_snapvault_init_commands(filer) )
            cmd_ns['commands'] += """<section>
            <title>SnapVault Initialisation</title>
            <screen><?db-font-size 60%% ?>%s</screen>
            </section>""" % cmds
            pass
        
        # Set up the snapvault schedules
        if filer.is_active_node:
            cmds = '\n'.join( self.command_gen.filer_snapvault_commands(filer) )
            cmd_ns['commands'] += """<section>
            <title>SnapVault Configuration</title>
            <screen>%s</screen>
            </section>""" % cmds

        # initialise the snapmirrors to the DR site
        if filer.is_active_node:
            log.debug("initialising snapmirror on %s", filer.name)

            cmds = '\n'.join( self.command_gen.filer_snapmirror_init_commands(filer) )
            if len(cmds) > 0:
                cmd_ns['commands'] += """<section>
                <title>SnapMirror Initialisation</title>
                <screen><?db-font-size 60%% ?>%s</screen>
                </section>""" % cmds
            else:
                log.debug("No SnapMirrors configured to filer '%s' at secondary site." % filer.name)

        # /etc/snapmirror additions
        if filer.is_active_node:
            cmds = self.command_gen.filer_etc_snapmirror_conf_commands(filer)
            if len(cmds) > 0:
                cmd_ns['commands'] += """<section>
                <title>Filer <filename>/etc/snapmirror.conf</filename></title>
                <para>Use these commands to append to the Filer's /etc/snapmirror.conf file:</para>
                <screen><?db-font-size 60%% ?>%s</screen>
                </section>""" % '\n'.join(cmds)

        # Add default route
        if filer.is_active_node:                
            title, cmds = self.command_gen.default_route_command(filer, vfiler)
            cmd_ns['commands'] += """<section>
            <title>%s</title>
            <screen>%s</screen>
            </section>""" % (title, '\n'.join( cmds ) )

        # Add services vlan routes if required
        if filer.is_active_node:                
            services_vlans = self.project.get_services_vlans(filer.site)
            if len(services_vlans) > 0:
                cmds = self.command_gen.services_vlan_route_commands(vfiler)
                cmd_ns['commands'] += """<section>
                <title>Services VLAN routes</title>
                <para>Use these commands to add routes into Services VLANs:</para>
                <screen>%s</screen>
                </section>""" % '\n'.join( cmds )
                pass
            pass

        # /etc/hosts additions
        if filer.is_active_node and filer.type == 'filer':
            cmds = self.command_gen.vfiler_etc_hosts_commands(filer, vfiler)
            cmd_ns['commands'] += """<section>
            <title>vFiler <filename>/etc/hosts</filename></title>
            <para>Use these commands to create the vFiler's /etc/hosts file:</para>
            <screen>%s</screen>
            </section>""" % '\n'.join(cmds)

        #
        # The /etc/rc file needs certain pieces of configuration added to it
        # to make the configuration persistent.
        #
        cmds = self.command_gen.filer_etc_rc_commands(filer, vfiler)
##         cmds = self.command_gen.vlan_create_commands(filer, vfiler)
##         cmds += self.command_gen.vfiler_add_storage_interface_commands(filer, vfiler)
##         title, cmdlist = self.command_gen.default_route_command(filer, vfiler)
##         cmds += cmdlist
##         cmds += self.command_gen.services_vlan_route_commands(vfiler)

        cmd_ns['commands'] += """<section>
        <title>Filer <filename>/etc/rc</filename> Additions</title>
        <para>Use these commands to make the new vFiler configuration persistent across reboots:</para>
        <screen>%s</screen>
        </section>""" % '\n'.join( cmds )

        # NFS exports are only configured on primary filers
        # FIXME: defaults configurable
        if filer.is_active_node and filer.type == 'filer':
            cmdlist = self.command_gen.vfiler_nfs_exports_commands(filer, vfiler)

            # Only add the section if NFS commands exist
            if len(cmdlist) == 0:
                log.debug("No NFS exports defined.")
            else:
                wrapped_lines = []
                for line in cmdlist:
                    if len(line) > 90:
                        wraplines = textwrap.wrap(line, 90)
                        wrapped_lines.append('\\\n'.join(wraplines))
                        pass
                    else:
                        wrapped_lines.append(line)

                cmds = '\n'.join( wrapped_lines )
                cmd_ns['commands'] += """<section>
                <title>NFS Exports Configuration</title>
                <screen><?db-font-size 60%% ?>%s</screen>
                </section>""" % cmds

        # CIFS exports are only configured on primary filers
        if 'cifs' in vfiler.get_allowed_protocols():
            if filer.is_active_node:
                cmds = self.command_gen.vfiler_cifs_dns_commands(vfiler)
                cmd_ns['commands'] += """<section>
                <title>CIFS DNS Configuration</title>
                <para>Use these commands to configure the vFiler for DNS:</para>
                <screen>%s</screen>
                </section>""" % '\n'.join(cmds)
                pass
            
            # Set up CIFS in the vFiler
            if filer.is_active_node:
                cmds = ['vfiler run %s cifs setup' % vfiler.name]
                cmd_ns['commands'] += """<section>
                <title>Set Up CIFS</title>
                <para>Set up CIFS for the vFiler. This is an interactive process.</para>
                <screen>%s</screen>
                </section>""" % '\n'.join(cmds)

            # Set up CIFS shares
            if filer.is_active_node and filer.type == 'filer':
                cmds = self.command_gen.vfiler_cifs_shares_commands(vfiler)
                cmd_ns['commands'] += """<section>
                <title>CIFS Share Configuration</title>
                <para>Set up CIFS for the vFiler. This is an interactive process.</para>
                <screen>%s</screen>
                </section>""" % '\n'.join(cmds)

        # iSCSI exports are only configured on primary filers
        if 'iscsi' in vfiler.get_allowed_protocols():
            if filer.is_active_node and filer.type == 'filer':

                # iSCSI CHAP configuration
                title, cmds = self.command_gen.vfiler_iscsi_chap_enable_commands(filer, vfiler, prefix=ns['iscsi_prefix'])
                cmd_ns['commands'] += """<section>
                <title>%s</title>
                <screen>%s</screen>
                </section>""" % (title, '\n'.join(cmds) )

                # iSCSI iGroup configuration
                title, cmds = self.command_gen.vfiler_igroup_enable_commands(filer, vfiler)
                if len(cmds) > 0:
                    cmd_ns['commands'] += """<section>
                    <title>%s</title>
                    <screen><?db-font-size 60%% ?>%s</screen>
                    </section>""" % (title, '\n'.join(cmds) )

                # iSCSI LUN configuration
                title, cmds = self.command_gen.vfiler_lun_enable_commands(filer, vfiler)
                if len(cmds) > 0:
                    cmd_ns['commands'] += """<section>
                    <title>%s</title>
                    <screen><?db-font-size 60%% ?>%s</screen>
                    </section>""" % (title, '\n'.join(cmds) )
                    pass
                pass
            pass
        # Finally, set the vFiler options.
        # Some options require previous pieces of configuration to exist before they work.
        # eg: dns.enable on requires /etc/resolv.conf to exist.
        if filer.is_active_node:
            cmds = '\n'.join( self.command_gen.vfiler_set_options_commands(vfiler, ns) )
            cmd_ns['commands'] += """<section>
            <title>vFiler Options</title>
            <screen>%s</screen>
            </section>""" % cmds

        return section.safe_substitute(cmd_ns)
