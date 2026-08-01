import React from "react";
import { Route, Switch } from "react-router-dom";
import AppliedRoute from "./components/AppliedRoute";
import Home from "./containers/Home";
import EmailDelivery from "./containers/EmailDelivery";
import Login from "./containers/Login";
import Activate from "./containers/Activate";
import Reset from "./containers/Reset";
import EmailReset from "./containers/EmailReset";
import Frontends from "./containers/Frontends";
import Frontend from "./containers/Frontend";
import GalleryTemplates from "./containers/GalleryTemplates";
import GalleryTemplate from "./containers/GalleryTemplate";
import FormTemplates from "./containers/FormTemplates";
import FormTemplate from "./containers/FormTemplate";
import BeefreeTemplates from './containers/BeefreeTemplates';
import BeefreeTemplate from './containers/BeefreeTemplate';
import Policies from "./containers/Policies";
import PolicyDomains from "./containers/PolicyDomains";
import PolicySettings from "./containers/PolicySettings";
import PolicyDeferrals from "./containers/PolicyDeferrals";
import PolicyServers from "./containers/PolicyServers";
import PolicyServerEdit from "./containers/PolicyServerEdit";
import DomainGroups from "./containers/DomainGroups";
import DomainGroup from "./containers/DomainGroup";
import Servers from "./containers/Servers";
import Server from "./containers/Server";
import ServerStats from "./containers/ServerStats";
import DKIM from "./containers/DKIM";
import Warmups from "./containers/Warmups";
import Warmup from "./containers/Warmup";
import Mailgun from "./containers/Mailgun";
import MailgunEdit from "./containers/MailgunEdit";
import SES from "./containers/SES";
import SESEdit from "./containers/SESEdit";
import SparkPost from "./containers/SparkPost";
import SparkPostEdit from "./containers/SparkPostEdit";
import Easylink from "./containers/Easylink";
import EasylinkEdit from "./containers/EasylinkEdit";
import SMTPRelays from "./containers/SMTPRelays";
import SMTPRelayEdit from "./containers/SMTPRelayEdit";
import Routes from "./containers/Routes";
import RouteEdit from "./containers/Route";
import Customers from "./containers/Customers";
import Customer from "./containers/Customer";
import CustomerUsers from "./containers/CustomerUsers";
import CustomerListApproval from "./containers/CustomerListApproval";
import IPReputation from "./containers/IPReputation";
import IPDelivery from "./containers/IPDelivery";
import AdminLog from "./containers/AdminLog";
import CustBCs from "./containers/CustBCs";
import CustBCsByBC from "./containers/CustBCsByBC";
import StatMsgs from "./containers/StatMsgs";
import User from "./containers/User";
import ChangePass from "./containers/ChangePass";
import OpenTicket from "./containers/OpenTicket";
import Welcome from "./containers/Welcome";
import CustomDomains from "./containers/CustomDomains";
import DomainThrottles from "./containers/DomainThrottles";
import DomainThrottle from "./containers/DomainThrottle";
import Contacts from "./containers/Contacts";
import ContactList from "./containers/ContactList";
import ContactsAdd from "./containers/ContactsAdd";
import ContactsAddUnsubs from "./containers/ContactsAddUnsubs";
import ContactsFind from "./containers/ContactsFind";
import ContactsDomains from "./containers/ContactsDomains";
import ContactsAllTags from "./containers/ContactsAllTags";
import ContactsRetrieval from "./containers/ContactsRetrieval";
import Segments from "./containers/Segments";
import Segment from "./containers/Segment";
import Suppression from "./containers/Suppression";
import SuppressionNew from "./containers/SuppressionNew";
import SuppressionEdit from "./containers/SuppressionEdit";
import Exclusion from "./containers/Exclusion";
import ExclusionAdd from "./containers/ExclusionAdd";
import Exports from "./containers/Exports";
import Broadcasts from "./containers/Broadcasts";
import BroadcastSummary from "./containers/BroadcastSummary";
import BroadcastHeatmap from "./containers/BroadcastHeatmap";
import BroadcastDomains from "./containers/BroadcastDomains";
import BroadcastMessages from "./containers/BroadcastMessages";
import BroadcastSummarySettings from "./containers/BroadcastSummarySettings";
import BroadcastSettings from "./containers/BroadcastSettings";
import BroadcastTemplate from "./containers/BroadcastTemplate";
import BroadcastRcpt from "./containers/BroadcastRcpt";
import BroadcastReview from "./containers/BroadcastReview";
import BroadcastUpdate from "./containers/BroadcastUpdate";
import BroadcastDetails from "./containers/BroadcastDetails";
import Funnels from "./containers/Funnels";
import FunnelSettings from "./containers/FunnelSettings";
import FunnelMessage from "./containers/FunnelMessage";
import FunnelMessageEdit from "./containers/FunnelMessageEdit";
import FunnelMessageStats from "./containers/FunnelMessageStats";
import Automations from "./containers/Automations";
import Automation from "./containers/Automation";
import AutomationEmail from "./containers/AutomationEmail";
import AutomationProcessingStatus from "./containers/AutomationProcessingStatus";
import AutomationTriggerEvents from "./containers/AutomationTriggerEvents";
import DebugEmailLogs from "./containers/DebugEmailLogs";
import Transactional from "./containers/Transactional";
import TransactionalTag from "./containers/TransactionalTag";
import TransactionalDomains from "./containers/TransactionalDomains";
import TransactionalMessages from "./containers/TransactionalMessages";
import TransactionalTemplates from "./containers/TransactionalTemplates";
import TransactionalTemplate from "./containers/TransactionalTemplate";
import TransactionalTemplateNew from "./containers/TransactionalTemplateNew";
import TransactionalLog from "./containers/TransactionalLog";
import TransactionalSettings from "./containers/TransactionalSettings";
import ConnectAPI from "./containers/ConnectAPI";
import ConnectSMTP from "./containers/ConnectSMTP";
import WebHooks from "./containers/WebHooks";
import WebHookEdit from "./containers/WebHookEdit";
import Zapier from "./containers/Zapier";
import Pabbly from "./containers/Pabbly";
import Forms from "./containers/Forms";
import Form from "./containers/Form";
import FormNew from "./containers/FormNew";
import FormName from "./containers/FormName";
import NotFound from "./containers/NotFound";
import ContactEdit from "./containers/ContactEdit";
import SignupSettings from "./containers/SignupSettings";

export default ({ childProps }) => {
  return (
  <Switch>
    <AppliedRoute path="/" exact component={Home} props={childProps} />
    <AppliedRoute path="/emaildelivery" exact component={EmailDelivery} props={childProps} />
    <AppliedRoute path="/login" exact component={Login} props={childProps} />
    <AppliedRoute path="/activate" exact component={Activate} props={childProps} />
    <AppliedRoute path="/reset" exact component={Reset} props={childProps} />
    <AppliedRoute path="/emailreset" exact component={EmailReset} props={childProps} />
    <AppliedRoute path="/frontends" exact component={Frontends} props={childProps} />
    <AppliedRoute path="/frontends/edit" exact component={Frontend} props={childProps} />
    <AppliedRoute path="/gallerytemplates" exact component={GalleryTemplates} props={childProps} />
    <AppliedRoute path="/gallerytemplates/edit" exact component={GalleryTemplate} props={childProps} />
    <AppliedRoute path="/formtemplates" exact component={FormTemplates} props={childProps} />
    <AppliedRoute path="/formtemplates/edit" exact component={FormTemplate} props={childProps} />
    <AppliedRoute path="/beefreetemplates" exact component={BeefreeTemplates} props={childProps} />
    <AppliedRoute path="/beefreetemplates/edit" exact component={BeefreeTemplate} props={childProps} />
    <AppliedRoute path="/policies" exact component={Policies} props={childProps} />
    <AppliedRoute path="/policies/domains" exact component={PolicyDomains} props={childProps} />
    <AppliedRoute path="/policies/settings" exact component={PolicySettings} props={childProps} />
    <AppliedRoute path="/policies/deferrals" exact component={PolicyDeferrals} props={childProps} />
    <AppliedRoute path="/policies/servers" exact component={PolicyServers} props={childProps} />
    <AppliedRoute path="/policies/servers/edit" exact component={PolicyServerEdit} props={childProps} />
    <AppliedRoute path="/domaingroups" exact component={DomainGroups} props={childProps} />
    <AppliedRoute path="/domaingroups/edit" exact component={DomainGroup} props={childProps} />
    <AppliedRoute path="/servers" exact component={Servers} props={childProps} />
    <AppliedRoute path="/servers/edit" exact component={Server} props={childProps} />
    <AppliedRoute path="/servers/stats" exact component={ServerStats} props={childProps} />
    <AppliedRoute path="/dkim" exact component={DKIM} props={childProps} />
    <AppliedRoute path="/warmups" exact component={Warmups} props={childProps} />
    <AppliedRoute path="/warmups/edit" exact component={Warmup} props={childProps} />
    <AppliedRoute path="/mailgun" exact component={Mailgun} props={childProps} />
    <AppliedRoute path="/mailgun/edit" exact component={MailgunEdit} props={childProps} />
    <AppliedRoute path="/ses" exact component={SES} props={childProps} />
    <AppliedRoute path="/ses/edit" exact component={SESEdit} props={childProps} />
    <AppliedRoute path="/sparkpost" exact component={SparkPost} props={childProps} />
    <AppliedRoute path="/sparkpost/edit" exact component={SparkPostEdit} props={childProps} />
    <AppliedRoute path="/easylink" exact component={Easylink} props={childProps} />
    <AppliedRoute path="/easylink/edit" exact component={EasylinkEdit} props={childProps} />
    <AppliedRoute path="/smtprelays" exact component={SMTPRelays} props={childProps} />
    <AppliedRoute path="/smtprelays/edit" exact component={SMTPRelayEdit} props={childProps} />
    <AppliedRoute path="/routes" exact component={Routes} props={childProps} />
    <AppliedRoute path="/routes/edit" exact component={RouteEdit} props={childProps} />
    <AppliedRoute path="/customers" exact component={Customers} props={childProps} />
    <AppliedRoute path="/customers/edit" exact component={Customer} props={childProps} />
    <AppliedRoute path="/customers/edit-users" exact component={CustomerUsers} props={childProps} />
    <AppliedRoute path="/customers/list-approval" exact component={CustomerListApproval} props={childProps} />
    <AppliedRoute path="/ipreputation" exact component={IPReputation} props={childProps} />
    <AppliedRoute path="/ipdelivery" exact component={IPDelivery} props={childProps} />
    <AppliedRoute path="/adminlog" exact component={AdminLog} props={childProps} />
    <AppliedRoute path="/custbcs" exact component={CustBCs} props={childProps} />
    <AppliedRoute path="/custbcsbybc" exact component={CustBCsByBC} props={childProps} />
    <AppliedRoute path="/statmsgs" exact component={StatMsgs} props={childProps} />
    <AppliedRoute path="/user" exact component={User} props={childProps} />
    <AppliedRoute path="/changepass" exact component={ChangePass} props={childProps} />
    <AppliedRoute path="/openticket" exact component={OpenTicket} props={childProps} />
    <AppliedRoute path="/welcome" exact component={Welcome} props={childProps} />
    <AppliedRoute path="/customdomains" exact component={CustomDomains} props={childProps} />
    <AppliedRoute path="/domainthrottles" exact component={DomainThrottles} props={childProps} />
    <AppliedRoute path="/domainthrottles/edit" exact component={DomainThrottle} props={childProps} />
    <AppliedRoute path="/contacts" exact component={Contacts} props={childProps} />
    <AppliedRoute path="/contacts/edit" exact component={ContactList} props={childProps} />
    <AppliedRoute path="/contacts/domains" exact component={ContactsDomains} props={childProps} />
    <AppliedRoute path="/contacts/add" exact component={ContactsAdd} props={childProps} />
    <AppliedRoute path="/contacts/addunsubs" exact component={ContactsAddUnsubs} props={childProps} />
    <AppliedRoute path="/contacts/find" exact component={ContactsFind} props={childProps} />
    <AppliedRoute path="/contacts/alltags" exact component={ContactsAllTags} props={childProps} />
    <AppliedRoute path="/contacts/retrieval" exact component={ContactsRetrieval} props={childProps} />
    <AppliedRoute path="/contacts/editcontact" exact component={ContactEdit} props={childProps} />
    <AppliedRoute path="/segments" exact component={Segments} props={childProps} />
    <AppliedRoute path="/segments/edit" exact component={Segment} props={childProps} />
    <AppliedRoute path="/suppression" exact component={Suppression} props={childProps} />
    <AppliedRoute path="/suppression/new" exact component={SuppressionNew} props={childProps} />
    <AppliedRoute path="/suppression/edit" exact component={SuppressionEdit} props={childProps} />
    <AppliedRoute path="/exclusion" exact component={Exclusion} props={childProps} />
    <AppliedRoute path="/exclusion/add" exact component={ExclusionAdd} props={childProps} />
    <AppliedRoute path="/exports" exact component={Exports} props={childProps} />
    <AppliedRoute path="/broadcasts" exact component={Broadcasts} props={childProps} />
    <AppliedRoute path="/broadcasts/summary" exact component={BroadcastSummary} props={childProps} />
    <AppliedRoute path="/broadcasts/heatmap" exact component={BroadcastHeatmap} props={childProps} />
    <AppliedRoute path="/broadcasts/domains" exact component={BroadcastDomains} props={childProps} />
    <AppliedRoute path="/broadcasts/messages" exact component={BroadcastMessages} props={childProps} />
    <AppliedRoute path="/broadcasts/summarysettings" exact component={BroadcastSummarySettings} props={childProps} />
    <AppliedRoute path="/broadcasts/settings" exact component={BroadcastSettings} props={childProps} />
    <AppliedRoute path="/broadcasts/template" exact component={BroadcastTemplate} props={childProps} />
    <AppliedRoute path="/broadcasts/rcpt" exact component={BroadcastRcpt} props={childProps} />
    <AppliedRoute path="/broadcasts/review" exact component={BroadcastReview} props={childProps} />
    <AppliedRoute path="/broadcasts/update" exact component={BroadcastUpdate} props={childProps} />
    <AppliedRoute path="/broadcasts/details" exact component={BroadcastDetails} props={childProps} />
    <AppliedRoute path="/funnels" exact component={Funnels} props={childProps} />
    <AppliedRoute path="/funnels/settings" exact component={FunnelSettings} props={childProps} />
    <AppliedRoute path="/funnels/message" exact component={FunnelMessage} props={childProps} />
    <AppliedRoute path="/funnels/message/edit" exact component={FunnelMessageEdit} props={childProps} />
    <AppliedRoute path="/funnels/message/stats" exact component={FunnelMessageStats} props={childProps} />
    <AppliedRoute path="/automations" exact component={Automations} props={childProps} />
    <AppliedRoute path="/automations/:automation_id/emails/:email_id" exact component={AutomationEmail} props={childProps} />
    <AppliedRoute path="/automations/:id" exact component={Automation} props={childProps} />
    <AppliedRoute path="/automation-processing-status" exact component={AutomationProcessingStatus} props={childProps} />
    <AppliedRoute path="/automation-trigger-events" exact component={AutomationTriggerEvents} props={childProps} />
    <AppliedRoute path="/debug-email-logs" exact component={DebugEmailLogs} props={childProps} />
    <AppliedRoute path="/transactional" exact component={Transactional} props={childProps} />
    <AppliedRoute path="/transactional/tag" exact component={TransactionalTag} props={childProps} />
    <AppliedRoute path="/transactional/domains" exact component={TransactionalDomains} props={childProps} />
    <AppliedRoute path="/transactional/messages" exact component={TransactionalMessages} props={childProps} />
    <AppliedRoute path="/transactional/templates" exact component={TransactionalTemplates} props={childProps} />
    <AppliedRoute path="/transactional/templates/edit" exact component={TransactionalTemplate} props={childProps} />
    <AppliedRoute path="/transactional/templates/new" exact component={TransactionalTemplateNew} props={childProps} />
    <AppliedRoute path="/transactional/log" exact component={TransactionalLog} props={childProps} />
    <AppliedRoute path="/transactional/settings" exact component={TransactionalSettings} props={childProps} />
    <AppliedRoute path="/connect" exact component={ConnectAPI} props={childProps} />
    <AppliedRoute path="/connect/smtp" exact component={ConnectSMTP} props={childProps} />
    <AppliedRoute path="/webhooks" exact component={WebHooks} props={childProps} />
    <AppliedRoute path="/webhooks/edit" exact component={WebHookEdit} props={childProps} />
    <AppliedRoute path="/zapier" exact component={Zapier} props={childProps} />
    <AppliedRoute path="/pabbly" exact component={Pabbly} props={childProps} />
    <AppliedRoute path="/forms" exact component={Forms} props={childProps} />
    <AppliedRoute path="/forms/edit" exact component={Form} props={childProps} />
    <AppliedRoute path="/forms/name" exact component={FormName} props={childProps} />
    <AppliedRoute path="/forms/new" exact component={FormNew} props={childProps} />
    <AppliedRoute path="/signupsettings" exact component={SignupSettings} props={childProps} />
    <Route component={NotFound} />
  </Switch>
  );
}
