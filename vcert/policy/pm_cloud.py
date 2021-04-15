#
# Copyright 2021 Venafi, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from vcert.common import Policy as Cit, AppDetails
from vcert.errors import VenafiError
from vcert.policy import RPA, ALLOW_ALL, DEFAULT_CA, DEFAULT_MAX_VALID_DAYS
from vcert.policy.policy_spec import Policy, Subject, KeyPair, DefaultSubject, DefaultKeyPair, PolicySpecification, \
    Defaults

supported_rsa_key_sizes = [1024, 2048, 4096]


def build_policy_spec(cit):
    """
    :param Cit cit:
    :rtype: PolicySpecification
    """
    if not cit:
        raise VenafiError("Certificate issuing template is empty")

    ps = PolicySpecification()
    p = Policy()
    p.domains = cit.SubjectCRegexes if len(cit.SubjectCRegexes) > 0 else None
    p.certificate_authority = cit.cert_authority_account_id if cit.cert_authority_account_id else None
    if cit.validity_period:
        # getting days in format P#D
        days = cit.validity_period[1:len(cit.validity_period)-1]
        int_value = int(days)
        p.max_valid_days = int_value

    s = Subject()
    create_subject = False
    if len(cit.SubjectORegexes) > 0:
        create_subject = True
        s.orgs = cit.SubjectORegexes
    if len(cit.SubjectOURegexes) > 0:
        create_subject = True
        s.org_units = cit.SubjectOURegexes
    if len(cit.SubjectLRegexes) > 0:
        create_subject = True
        s.localities = cit.SubjectLRegexes
    if len(cit.SubjectSTRegexes) > 0:
        create_subject = True
        s.states = cit.SubjectSTRegexes
    if len(cit.SubjectCRegexes) > 0:
        create_subject = True
        s.countries = cit.SubjectCRegexes

    p.subject = s if create_subject else None

    kp = KeyPair()
    create_kp = False
    if len(cit.key_types) > 0:
        key_types = []
        key_sizes = []
        for allowed_kt in cit.key_types:
            kt = allowed_kt.key_type
            kl = allowed_kt.option
            key_types.append(kt)
            key_sizes.append(kl)
        create_kp = True
        kp.key_types = key_types
        kp.rsa_key_sizes = key_sizes

    kp.reuse_allowed = cit.key_reuse
    p.key_pair = kp if create_kp else None
    ps.policy = p

    rs = cit.recommended_settings
    if rs:
        d = Defaults()
        ds = DefaultSubject()
        create_ds = False
        if rs.subjectOValue:
            ds.org = rs.subjectOValue
            create_ds = True
        if rs.subjectOUValue:
            ds.org_units = [rs.subjectOUValue]
            create_ds = True
        if rs.subjectLValue:
            ds.locality = rs.subjectLValue
            create_ds = True
        if rs.subjectSTValue:
            ds.state = rs.subjectSTValue
            create_ds = True
        if rs.subjectCValue:
            ds.country = rs.subjectCValue
            create_ds = True

        d.subject = ds if create_ds else None

        kt = rs.keyType
        if kt:
            dkp = DefaultKeyPair()
            create_dkp = False
            if kt.key_type:
                dkp.key_type = kt.key_type
                create_dkp = True
            if kt.option:
                dkp.rsa_key_size = kt.option
                create_dkp = True
            d.key_pair = dkp if create_dkp else None

        ps.defaults = d
    return ps


def validate_policy_spec(policy_spec):
    """
    :param PolicySpecification policy_spec:
    """
    default_error_msg = 'Default value does not match with policy values.' \
                        '\nAttribute: %s\nDefault value:%s\nPolicy values:%s'
    # validate policy values
    if policy_spec.policy:
        p = policy_spec.policy

        # validate key pair values
        if policy_spec.policy.key_pair:
            if len(policy_spec.policy.key_pair.key_types) > 1:
                raise VenafiError('Key Type values exceeded. Only one Key Type is allowed by Venafi Cloud')

            if policy_spec.policy.key_pair.key_types[0] != 'RSA':
                raise VenafiError('Key Type [%s] is not supported by Venafi Cloud', p.key_pair.key_types[0])

            if len(policy_spec.policy.key_pair.rsa_key_sizes) > 0:
                invalid_value = get_invalid_cloud_rsa_key_size_value(policy_spec.policy.key_pair.rsa_key_sizes)
                if invalid_value:
                    raise VenafiError('The Key Size [%d] is not supported by Venafi Cloud', invalid_value)

        # validate subject CN and SAN regexes
        if p.subject_alt_names:
            sans = get_sans(policy_spec.policy.subject_alt_names)
            if len(sans) > 0:
                for k, v in sans:
                    if v is True:
                        raise VenafiError('Subject Alt name [%s] is not allowed by Venafi Cloud', k)

        # validate default subject values against policy values
        if policy_spec.defaults and policy_spec.defaults.subject and policy_spec.policy.subject:
            ds = policy_spec.defaults.subject
            s = policy_spec.policy.subject

            if ds.org and len(s.orgs) > 0:
                if not is_valid_policy_value(s.orgs, ds.org):
                    raise VenafiError(default_error_msg % ('Organization', ds.org, s.orgs))

            if ds.org_units and len(ds.org_units) > 0 and len(s.org_units) > 0:
                if not member_of(ds.org_units, s.org_units):
                    raise VenafiError(default_error_msg % ('Org Units', ds.org_units, s.org_units))

            if ds.locality and len(s.localities) > 0:
                if not is_valid_policy_value(s.localities, ds.locality):
                    raise VenafiError(default_error_msg % ('Localities', ds.locality, s.localities))

            if ds.state and len(s.states) > 0:
                if not is_valid_policy_value(s.states, ds.state):
                    raise VenafiError(default_error_msg % ('States', ds.state, s.states))

            if ds.country and len(s.countries) > 0:
                if not is_valid_policy_value(s.countries, ds.country):
                    raise VenafiError(default_error_msg % ('Countries', ds.country, s.countries))

        # validate default key pair values against policy values
        if policy_spec.defaults and policy_spec.defaults.key_pair and policy_spec.policy.key_pair:
            dkp = policy_spec.defaults.key_pair
            kp = policy_spec.policy.key_pair

            if dkp.key_type and len(kp.key_types) > 0:
                if dkp.key_type not in kp.key_types:
                    raise VenafiError(default_error_msg % ('Key Types', dkp.key_type, kp.key_types))

            if dkp.rsa_key_size and len(kp.rsa_key_sizes) > 0:
                if dkp.rsa_key_size not in kp.rsa_key_sizes:
                    raise VenafiError(default_error_msg % ('RSA Key Sizes', dkp.rsa_key_size, kp.rsa_key_sizes))

            if dkp.elliptic_curve and len(kp.elliptic_curves) > 0:
                if dkp.elliptic_curve not in kp.elliptic_curves:
                    raise VenafiError(default_error_msg % ('Elliptic Curves', dkp.elliptic_curve, kp.elliptic_curves))

            if dkp.service_generated is not None and kp.service_generated is not None:
                if dkp.service_generated != kp.service_generated:
                    raise VenafiError(
                        default_error_msg % ('Service Generated', dkp.service_generated, kp.service_generated))

    # validate default values when policy is not defined
    if policy_spec.defaults and policy_spec.defaults.key_pair:
        dkp = policy_spec.defaults.key_pair

        if dkp.key_type and dkp.key_type != "RSA":
            raise VenafiError('Default Key Type [%s] is not supported by Venafi Cloud', dkp.key_type)

        if dkp.rsa_key_size:
            invalid_value = get_invalid_cloud_rsa_key_size_value([dkp.rsa_key_size])
            if invalid_value:
                raise VenafiError('Default Key Size [%d] is not supported by Venafi Cloud', invalid_value)


def get_invalid_cloud_rsa_key_size_value(rsa_keys):
    """
    :param list[int] rsa_keys:
    :rtype: int
    """
    for v in rsa_keys:
        if v not in supported_rsa_key_sizes:
            return v
    return None


def get_sans(names):
    """
    :param SubjectAltNames names:
    :rtype: dict
    """
    sans = dict
    if names.dns_allowed is not None:
        sans[RPA.TPP_DNS_ALLOWED] = names.dns_allowed
    if names.ip_allowed is not None:
        sans[RPA.TPP_IP_ALLOWED] = names.ip_allowed
    if names.email_allowed is not None:
        sans[RPA.TPP_EMAIL_ALLOWED] = names.email_allowed
    if names.upn_allowed is not None:
        sans[RPA.TPP_UPN_ALLOWED] = names.upn_allowed
    if names.uri_allowed is not None:
        sans[RPA.TPP_URI_ALLOWED] = names.uri_allowed

    return sans


def is_valid_policy_value(policy_values, default_value):
    """
    :param list[str] policy_values:
    :param str default_value:
    :rtype: bool
    """
    if len(policy_values) == 1 and policy_values[0] == ALLOW_ALL:
        return True
    return True if default_value in policy_values else False


def member_of(values, collection):
    """
    :param list[str] values:
    :param list[str] collection:
    :rtype: bool
    """
    if len(values) == 1 and values[0] == ALLOW_ALL:
        return True
    return True if all(x in values for x in collection) else False


def get_ca_details(ca_name):
    """
    :param str ca_name:
    """
    data = ca_name.split("\\")
    if len(data) < 3:
        raise VenafiError('Certificate Authority name invalid [%s]', ca_name)

    return CertificateAuthorityInfo(data[0], data[1], data[2])


def build_cit_request(ps):
    """
    :param PolicySpecification ps:
    :rtype: dict
    """
    request = dict()

    if ps.policy and ps.policy.certificate_authority:
        ca_str = ps.policy.certificate_authority
    else:
        ca_str = DEFAULT_CA

    cert_auth = get_ca_details(ca_str)

    request['certificateAuthority'] = cert_auth.ca_type

    if ps.policy and ps.policy.max_valid_days:
        validity = ps.policy.max_valid_days
    else:
        validity = DEFAULT_MAX_VALID_DAYS

    product = {
        'certificateAuthority': cert_auth.ca_type,
        'productName': cert_auth.vendor_name,
        'validityPeriod': ("P%dD", validity)
    }
    request['product'] = product

    if ps.policy and len(ps.policy.domains) > 0:
        regex_value = convert_to_regex(ps.policy.domains)
        request['subjectCNRegexes'] = regex_value
        if ps.policy.subject_alt_names and ps.policy.subject_alt_names.dns_allowed is not None:
            if ps.policy.subject_alt_names.dns_allowed:
                request['sanRegexes'] = regex_value
            else:
                request['sanRegexes'] = None
        else:
            request['sanRegexes'] = regex_value
    else:
        request['subjectCNRegexes'] = [ALLOW_ALL]
        request['sanRegexes'] = [ALLOW_ALL]

    if ps.policy and ps.policy.subject and len(ps.policy.subject.orgs) > 0:
        request['subjectORegexes'] = ps.policy.subject.orgs
    else:
        request['subjectORegexes'] = [ALLOW_ALL]

    if ps.policy and ps.policy.subject and len(ps.policy.subject.org_units) > 0:
        request['subjectOURegexes'] = ps.policy.subject.org_units
    else:
        request['subjectOURegexes'] = [ALLOW_ALL]

    if ps.policy and ps.policy.subject and len(ps.policy.subject.localities) > 0:
        request['subjectLRegexes'] = ps.policy.subject.localities
    else:
        request['subjectLRegexes'] = [ALLOW_ALL]

    if ps.policy and ps.policy.subject and len(ps.policy.subject.states) > 0:
        request['subjectSTRegexes'] = ps.policy.subject.states
    else:
        request['subjectSTRegexes'] = [ALLOW_ALL]

    if ps.policy and ps.policy.subject and len(ps.policy.subject.countries) > 0:
        request['subjectCValues'] = ps.policy.subject.countries
    else:
        request['subjectCValues'] = [ALLOW_ALL]

    key_types = dict()
    if ps.policy and ps.policy.key_pair and len(ps.policy.key_pair.key_types) > 0:
        key_types['keyType'] = ps.policy.key_pair.key_types[0]
    else:
        key_types['keyType'] = 'RSA'

    if ps.policy and ps.policy.key_pair and len(ps.policy.key_pair.rsa_key_sizes) > 0:
        key_types['keyLengths'] = ps.policy.key_pair.rsa_key_sizes
    elif ps.defaults and ps.defaults.key_pair and ps.defaults.key_pair.rsa_key_size:
        key_types['keyLengths'] = [ps.defaults.key_pair.rsa_key_size]
    else:
        key_types['keyLengths'] = [2048]

    request['keyTypes'] = [key_types]

    if ps.policy and ps.policy.key_pair and ps.policy.key_pair.reuse_allowed:
        request['keyReuse'] = ps.policy.key_pair.reuse_allowed
    else:
        request['keyReuse'] = False

    r_settings = dict()
    if ps.defaults and ps.defaults.subject:
        if ps.defaults.subject.org:
            r_settings['subjectOValue'] = ps.defaults.subject.org
        if ps.defaults.subject.org_units:
            r_settings['subjectOUValue'] = ps.defaults.subject.org_units[0]
        if ps.defaults.subject.locality:
            r_settings['subjectLValue'] = ps.defaults.subject.locality
        if ps.defaults.subject.state:
            r_settings['subjectSTValue'] = ps.defaults.subject.state
        if ps.defaults.subject.country:
            r_settings['subjectCValue'] = ps.defaults.subject.country

    r_key = dict()
    if ps.defaults and ps.defaults.key_pair:
        if ps.defaults.key_pair.key_type:
            r_key['type'] = ps.defaults.key_pair.key_type
            if ps.defaults.key_pair.rsa_key_size:
                r_key['length'] = ps.defaults.key_pair.rsa_key_size
            else:
                r_key['length'] = 2048

    if r_key:
        r_settings['key'] = r_key

    if r_settings:
        r_settings['keyReuse'] = False
        request['recommendedSettings'] = r_settings

    return request


def convert_to_regex(domains, wildcard_allowed):
    """
    :param dict[str] domains:
    :param bool wildcard_allowed:
    :rtype: dict
    """
    list = []
    for d in domains:
        current = d.replace('.', '\\.')
        if wildcard_allowed:
            current = "[*a-z]{1}[a-z0-9.-]*\\." + current
        else:
            current = "[a-z]{1}[a-z0-9.-]*\\." + current
        list.append(current)
    return list


def build_app_update_request(app_details, cit_data):
    """
    :param AppDetails app_details:
    :param dict cit_data:
    :rtype: dict
    """
    app_request = {
        'ownerIdsAndTypes': app_details.owner_ids_and_types,
        'name': app_details.name,
        'description': app_details.description,
        'fqdns': app_details.fq_dns,
        'internalFqdns': app_details.internal_fq_dns,
        'internalIpRanges': app_details.internal_ip_ranges,
        'externalIpRanges': app_details.external_ip_ranges,
        'internalPorts': app_details.internal_ports,
        'fullyQualifiedDomainNames': app_details.fully_qualified_domain_names,
        'ipRanges': app_details.ip_ranges,
        'ports': app_details.ports,
        'organizationalUnitId': app_details.org_unit_id
    }

    cit_map = app_details.cit_alias_id_map
    # cit_name = cit_map[cit_data['name']] if cit_data['name'] in cit_map else None
    # if not cit_name or cit_name != cit_data['id']:
    cit_map[cit_data['name']] = cit_data['id']

    app_request['certificateIssuingTemplateAliasIdMap'] = cit_map
    return app_request


class CertificateAuthorityInfo:
    def __init__(self, ca_type, ca_acc_key, vendor_name):
        """
        :param str ca_type:
        :param str ca_acc_key:
        :param str vendor_name:
        """
        self.ca_type = ca_type
        self.ca_account_key = ca_acc_key
        self.vendor_name = vendor_name


class AccountDetails:
    def __init__(self, account, product_option):
        """
        :param Account account:
        :param list[ProductOption] product_option:
        """
        self.account = account
        self.product_option = product_option


class Account:
    def __init__(self, id, key):
        """
        :param str id:
        :param str key:
        """
        self.id = id
        self.key = key


class ProductOption:
    def __init__(self, name, id):
        """
        :param str name:
        :param str id:
        """
        self.product_name = name
        self.id = id


class UserDetails:
    def __init__(self, user=None, company=None, api_key=None):
        """
        :param user:
        :param company:
        :param api_key:
        """
        self.user = user
        self.company = company
        self.api_key = api_key


class User:
    def __init__(self, username=None, user_id=None, company_id=None, email=None, user_type=None, user_acc_type=None,
                 status=None, creation_date=None):
        """
        :param str username:
        :param str user_id:
        :param str company_id:
        :param str email:
        :param str user_type:
        :param str user_acc_type:
        :param str status:
        :param str creation_date:
        """
        self.username = username
        self.user_id = user_id
        self.company_id = company_id
        self.email = email
        self.user_type = user_type
        self.user_account_type = user_acc_type
        self.status = status
        self.creation_date = creation_date


class Company:
    def __init__(self, company_id, name, company_type=None, active=None, creation_date=None, domains=None):
        """
        :param str company_id:
        :param str name:
        :param str company_type:
        :param bool active:
        :param str creation_date:
        :param list[str] domains:
        """
        self.company_id = company_id
        self.name = name
        self.company_type = company_type
        self.active = active
        self.creation_date = creation_date
        self.domains = domains


class ApiKey:
    def __init__(self, username=None, api_types=None, api_version=None, apikey_status=None, creation_date=None,
                 validity_start_date=None, validity_end_date=None):
        """
        :param string username:
        :param list[str] api_types:
        :param str api_version:
        :param str apikey_status:
        :param str creation_date:
        :param str validity_start_date:
        :param str validity_end_date:
        """
        self.username = username
        self.api_types = api_types
        self.api_version = api_version
        self.apikey_status = apikey_status
        self.creation_date = creation_date
        self.validity_start_date = validity_start_date
        self.validity_end_date = validity_end_date


def build_user(data):
    """
    :param dict data:
    """
    return User(
        username=data['username'] if 'username' in data else None,
        user_id=data['id'] if 'id' in data else None,
        company_id=data['companyId'] if 'companyId' in data else None,
        email=data['emailAddress'] if 'emailAddress' in data else None,
        user_type=data['userType'] if 'userType' in data else None,
        user_acc_type=data['userAccountType'] if 'userAccountType' in data else None,
        status=data['userStatus'] if 'userStatus' in data else None,
        creation_date=data['creationDate'] if 'creationDate' in data else None
        )


def build_company(data):
    """
    :param dict data:
    """
    return Company(
        company_id=data['id'] if 'id' in data else None,
        name=data['name'] if 'name' in data else None,
        company_type=data['companyType'] if 'companyType' in data else None,
        active=data['active'] if 'active' in data else None,
        creation_date=data['creationDate'] if 'creationDate' in data else None,
        domains=data['domains'] if 'domains' in data else None,
    )


def build_apikey(data):
    """
    :param dict data:
    """
    return ApiKey(
        username=data['username'] if 'username' in data else None,
        api_types=data['apitypes'] if 'apitypes' in data else None,
        api_version=data['apiVersion'] if 'apiVersion' in data else None,
        apikey_status=data['apiKeyStatus'] if 'apiKeyStatus' in data else None,
        creation_date=data['creationDate'] if 'creationDate' in data else None,
        validity_start_date=data['validityStartDate'] if 'validityStartDate' in data else None,
        validity_end_date=data['validityEndDate'] if 'validityEndDate' in data else None,
    )
