--
-- PostgreSQL database dump
--

-- Dumped from database version 11.18
-- Dumped by pg_dump version 12.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: btree_gin; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS btree_gin WITH SCHEMA public;


--
-- Name: EXTENSION btree_gin; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION btree_gin IS 'support for indexing common datatypes in GIN';


--
-- Name: btree_gist; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;


--
-- Name: EXTENSION btree_gist; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION btree_gist IS 'support for indexing common datatypes in GiST';


--
-- Name: citext; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;


--
-- Name: EXTENSION citext; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION citext IS 'data type for case-insensitive character strings';


--
-- Name: cube; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS cube WITH SCHEMA public;


--
-- Name: EXTENSION cube; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION cube IS 'data type for multidimensional cubes';


--
-- Name: dblink; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS dblink WITH SCHEMA public;


--
-- Name: EXTENSION dblink; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION dblink IS 'connect to other PostgreSQL databases from within a database';


--
-- Name: dict_int; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS dict_int WITH SCHEMA public;


--
-- Name: EXTENSION dict_int; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION dict_int IS 'text search dictionary template for integers';


--
-- Name: earthdistance; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS earthdistance WITH SCHEMA public;


--
-- Name: EXTENSION earthdistance; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION earthdistance IS 'calculate great-circle distances on the surface of the Earth';


--
-- Name: fuzzystrmatch; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS fuzzystrmatch WITH SCHEMA public;


--
-- Name: EXTENSION fuzzystrmatch; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION fuzzystrmatch IS 'determine similarities and distance between strings';


--
-- Name: hstore; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS hstore WITH SCHEMA public;


--
-- Name: EXTENSION hstore; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION hstore IS 'data type for storing sets of (key, value) pairs';


--
-- Name: intarray; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS intarray WITH SCHEMA public;


--
-- Name: EXTENSION intarray; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION intarray IS 'functions, operators, and index support for 1-D arrays of integers';


--
-- Name: ltree; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS ltree WITH SCHEMA public;


--
-- Name: EXTENSION ltree; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION ltree IS 'data type for hierarchical tree-like structures';


--
-- Name: pg_stat_statements; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;


--
-- Name: EXTENSION pg_stat_statements; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_stat_statements IS 'track execution statistics of all SQL statements executed';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: pgrowlocks; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgrowlocks WITH SCHEMA public;


--
-- Name: EXTENSION pgrowlocks; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgrowlocks IS 'show row-level locking information';


--
-- Name: pgstattuple; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgstattuple WITH SCHEMA public;


--
-- Name: EXTENSION pgstattuple; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgstattuple IS 'show tuple-level statistics';


--
-- Name: tablefunc; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS tablefunc WITH SCHEMA public;


--
-- Name: EXTENSION tablefunc; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION tablefunc IS 'functions that manipulate whole tables, including crosstab';


--
-- Name: unaccent; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;


--
-- Name: EXTENSION unaccent; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION unaccent IS 'text search dictionary that removes accents';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


SET default_tablespace = '';

--
-- Name: alltags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alltags (
    cid text NOT NULL,
    tag text NOT NULL,
    added timestamp with time zone NOT NULL,
    count integer NOT NULL
);


--
-- Name: apiretries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.apiretries (
    id integer NOT NULL,
    cid text NOT NULL,
    type text NOT NULL,
    queuetype text NOT NULL,
    ts timestamp without time zone NOT NULL,
    retrytime timestamp without time zone NOT NULL,
    retries integer NOT NULL,
    error text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: apiretries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.apiretries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: apiretries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.apiretries_id_seq OWNED BY public.apiretries.id;


--
-- Name: campaign_browsers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_browsers (
    campaign_id text NOT NULL,
    os integer NOT NULL,
    browser integer NOT NULL,
    count integer NOT NULL
);


--
-- Name: campaign_devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_devices (
    campaign_id text NOT NULL,
    device integer NOT NULL,
    count integer NOT NULL
);


--
-- Name: campaign_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_domains (
    campaign_id text NOT NULL,
    domain text NOT NULL,
    count integer NOT NULL
);


--
-- Name: campaign_locations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_locations (
    campaign_id text NOT NULL,
    country_code text NOT NULL,
    country text NOT NULL,
    region text NOT NULL,
    count integer NOT NULL
);


--
-- Name: campaigns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaigns (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: camplogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.camplogs (
    campid text NOT NULL,
    email text NOT NULL,
    cmd text NOT NULL,
    ts timestamp without time zone NOT NULL,
    code text
);


--
-- Name: campqueue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campqueue (
    cid text NOT NULL,
    campid text NOT NULL,
    sendid text NOT NULL,
    count integer NOT NULL,
    remaining integer NOT NULL,
    data jsonb NOT NULL,
    domain text NOT NULL
);


--
-- Name: clientdkim; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.clientdkim (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: companies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.companies (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: company_list_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_list_group (
    parent_cid text NOT NULL,
    cid text NOT NULL
);


--
-- Name: companylimits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.companylimits (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: cookies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cookies (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: countries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.countries (
    country text NOT NULL
);


--
-- Name: datablocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.datablocks (
    path text NOT NULL,
    data bytea NOT NULL,
    modified timestamp without time zone NOT NULL
);


--
-- Name: dkimentries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dkimentries (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: dlq; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dlq (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: domaingroups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.domaingroups (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: domainthrottles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.domainthrottles (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: easylink; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.easylink (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: eltracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.eltracking (
    id text NOT NULL,
    settingsid text NOT NULL,
    ts timestamp without time zone NOT NULL
);


--
-- Name: exclusions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exclusions (
    cid text NOT NULL,
    item text NOT NULL,
    exclusionid text NOT NULL,
    rawhash bigint
);


--
-- Name: exports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exports (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: formcookies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formcookies (
    formid text NOT NULL,
    uid text NOT NULL,
    viewed_at timestamp with time zone,
    submitted_at timestamp with time zone
);


--
-- Name: forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forms (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: formtemplates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.formtemplates (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: frontends; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.frontends (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: funnelqueue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.funnelqueue (
    id bigint NOT NULL,
    email text NOT NULL,
    rawhash bigint NOT NULL,
    messageid text NOT NULL,
    ts timestamp without time zone NOT NULL,
    cid text NOT NULL,
    sent boolean DEFAULT false NOT NULL,
    domain text
);


--
-- Name: funnelqueue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.funnelqueue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: funnelqueue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.funnelqueue_id_seq OWNED BY public.funnelqueue.id;


--
-- Name: funnels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.funnels (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: gallerytemplates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gallerytemplates (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: hourstats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hourstats (
    id text NOT NULL,
    cid text NOT NULL,
    ts timestamp without time zone NOT NULL,
    sinkid text NOT NULL,
    domaingroupid text NOT NULL,
    ip text NOT NULL,
    settingsid text NOT NULL,
    campid text NOT NULL,
    complaint integer NOT NULL,
    open integer NOT NULL,
    send integer NOT NULL,
    soft integer NOT NULL,
    hard integer NOT NULL,
    err integer NOT NULL,
    defercnt integer NOT NULL,
    click integer NOT NULL,
    unsub integer NOT NULL,
    campcid text NOT NULL
);


--
-- Name: hourstats_backup; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hourstats_backup (
    id text NOT NULL,
    cid text,
    ts timestamp without time zone,
    sinkid text,
    domaingroupid text,
    ip text,
    settingsid text,
    campid text,
    complaint integer,
    open integer,
    send integer,
    soft integer,
    hard integer,
    err integer,
    defercnt integer,
    click integer,
    unsub integer,
    campcid text
);


--
-- Name: ipcities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ipcities (
    iprange int8range NOT NULL,
    loc_id integer NOT NULL
);


--
-- Name: iplimits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.iplimits (
    sinkid text NOT NULL,
    settingsid text NOT NULL,
    domain text NOT NULL,
    warmupid text,
    ip text NOT NULL,
    sendlimit bigint NOT NULL
);


--
-- Name: iplocations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.iplocations (
    iprange int8range NOT NULL,
    country_code text NOT NULL,
    country text NOT NULL,
    region text NOT NULL,
    zip text NOT NULL
);


--
-- Name: iplocs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.iplocs (
    id integer NOT NULL,
    countrycode text NOT NULL,
    country text NOT NULL,
    state text NOT NULL
);


--
-- Name: ippauses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ippauses (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.links (
    id text NOT NULL,
    url text NOT NULL,
    campaign text NOT NULL,
    index integer NOT NULL,
    track boolean NOT NULL
);


--
-- Name: list_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.list_domains (
    list_id text NOT NULL,
    domain text NOT NULL,
    count integer NOT NULL
);


--
-- Name: lists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lists (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: locks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locks (
    name text NOT NULL,
    ts timestamp without time zone NOT NULL
);


--
-- Name: mailgun; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mailgun (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: message_browsers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_browsers (
    message_id text NOT NULL,
    os integer NOT NULL,
    browser integer NOT NULL,
    count integer NOT NULL
);


--
-- Name: message_devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_devices (
    message_id text NOT NULL,
    device integer NOT NULL,
    count integer NOT NULL
);


--
-- Name: message_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_domains (
    message_id text NOT NULL,
    domain text NOT NULL,
    count integer NOT NULL
);


--
-- Name: message_locations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_locations (
    message_id text NOT NULL,
    country_code text NOT NULL,
    country text NOT NULL,
    region text NOT NULL,
    count integer NOT NULL
);


--
-- Name: messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.messages (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: mgtracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mgtracking (
    id text NOT NULL,
    ip text NOT NULL,
    settingsid text NOT NULL,
    ts timestamp without time zone NOT NULL
);


--
-- Name: oldlinks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oldlinks (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policies (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: regions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regions (
    country text NOT NULL,
    region text NOT NULL
);


--
-- Name: resthooks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resthooks (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: routes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routes (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: segments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.segments (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: sendlimits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sendlimits (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: ses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ses (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: sesmessages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sesmessages (
    id text NOT NULL,
    settingsid text NOT NULL,
    cid text NOT NULL,
    campid text NOT NULL,
    is_camp boolean NOT NULL,
    trackingid text NOT NULL,
    ts timestamp without time zone NOT NULL
);

--
-- Name: sinkdomainqueues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sinkdomainqueues (
    sinkid text NOT NULL,
    domain text NOT NULL,
    queue bigint NOT NULL
);


--
-- Name: sinks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sinks (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: smslinks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.smslinks (
    id text NOT NULL,
    data text NOT NULL,
    ts timestamp without time zone NOT NULL
);

--
-- Name: smtprelays; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.smtprelays (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);

--
-- Name: smtptracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.smtptracking (
    id text NOT NULL,
    settingsid text NOT NULL,
    ts timestamp without time zone NOT NULL
);

--
-- Name: sparkpost; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sparkpost (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: sptracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sptracking (
    id text NOT NULL,
    ip text NOT NULL,
    settingsid text NOT NULL,
    ts timestamp without time zone NOT NULL
);


--
-- Name: statlogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statlogs (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: statlogs2; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statlogs2 (
    id text NOT NULL,
    cid text,
    ip text,
    ts text,
    err integer,
    hard integer,
    send integer,
    soft integer,
    count integer,
    lastts text,
    sinkid text,
    deferlen integer,
    defermsg text,
    settingsid text,
    domaingroupid text
);


--
-- Name: statlogs_backup; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statlogs_backup (
    id text NOT NULL,
    cid text,
    data jsonb
);


--
-- Name: statmsgs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.statmsgs (
    id text NOT NULL,
    cid text NOT NULL,
    ts timestamp without time zone NOT NULL,
    sinkid text NOT NULL,
    domaingroupid text NOT NULL,
    ip text NOT NULL,
    settingsid text NOT NULL,
    campid text NOT NULL,
    message text NOT NULL,
    msgtype text NOT NULL,
    count integer NOT NULL
);


--
-- Name: supplists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supplists (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: tableconfigs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tableconfigs (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: taskgather; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taskgather (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: taskgatherdata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taskgatherdata (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: temp_indexl; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.temp_indexl
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.templates (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: tempusers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tempusers (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: testemails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.testemails (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: testlogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.testlogs (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: trumpiamessages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trumpiamessages (
    id text NOT NULL,
    settingsid text NOT NULL,
    cid text NOT NULL,
    campid text NOT NULL,
    is_camp boolean NOT NULL,
    trackingid text NOT NULL,
    ts timestamp without time zone NOT NULL
);


--
-- Name: txnlogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.txnlogs (
    tag text NOT NULL,
    msgid text NOT NULL,
    email text NOT NULL,
    cmd text NOT NULL,
    ts timestamp without time zone NOT NULL,
    code text
);


--
-- Name: txnqueue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.txnqueue (
    cid text NOT NULL,
    id bigint NOT NULL,
    data jsonb NOT NULL,
    route text,
    domain text
);


--
-- Name: txnqueue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.txnqueue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: txnqueue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.txnqueue_id_seq OWNED BY public.txnqueue.id;


--
-- Name: txnsends; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.txnsends (
    id text NOT NULL,
    cid text NOT NULL,
    ts timestamp without time zone NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: txnstatmsgs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.txnstatmsgs (
    id text NOT NULL,
    cid text NOT NULL,
    ts timestamp without time zone NOT NULL,
    tag text NOT NULL,
    domain text NOT NULL,
    message text NOT NULL,
    msgtype text NOT NULL,
    count integer NOT NULL
);


--
-- Name: txnstats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.txnstats (
    id text NOT NULL,
    cid text NOT NULL,
    ts timestamp without time zone NOT NULL,
    tag text NOT NULL,
    domain text NOT NULL,
    complaint integer NOT NULL,
    unsub integer NOT NULL,
    hard integer NOT NULL,
    soft integer NOT NULL,
    send integer NOT NULL,
    open integer NOT NULL,
    click integer NOT NULL,
    open_all integer NOT NULL,
    click_all integer NOT NULL
);


--
-- Name: txntags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.txntags (
    id text NOT NULL,
    cid text NOT NULL,
    tag text NOT NULL
);


--
-- Name: txntemplates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.txntemplates (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: unsublogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unsublogs (
    cid text NOT NULL,
    email text NOT NULL,
    rawhash bigint NOT NULL,
    unsubscribed boolean NOT NULL,
    complained boolean NOT NULL,
    bounced boolean NOT NULL
);


--
-- Name: userlogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.userlogs (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id text NOT NULL,
    cid text,
    data jsonb NOT NULL
);


--
-- Name: warmups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.warmups (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);


--
-- Name: webhooks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhooks (
    id text NOT NULL,
    cid text NOT NULL,
    data jsonb NOT NULL
);



--
-- Name: apiretries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apiretries ALTER COLUMN id SET DEFAULT nextval('public.apiretries_id_seq'::regclass);


--
-- Name: funnelqueue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.funnelqueue ALTER COLUMN id SET DEFAULT nextval('public.funnelqueue_id_seq'::regclass);


--
-- Name: txnqueue id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txnqueue ALTER COLUMN id SET DEFAULT nextval('public.txnqueue_id_seq'::regclass);


--
-- Name: alltags alltags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alltags
    ADD CONSTRAINT alltags_pkey PRIMARY KEY (cid, tag);


--
-- Name: apiretries apiretries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apiretries
    ADD CONSTRAINT apiretries_pkey PRIMARY KEY (id);


--
-- Name: campaign_browsers campaign_browsers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_browsers
    ADD CONSTRAINT campaign_browsers_pkey PRIMARY KEY (campaign_id, os, browser);


--
-- Name: campaign_devices campaign_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_devices
    ADD CONSTRAINT campaign_devices_pkey PRIMARY KEY (campaign_id, device);


--
-- Name: campaign_domains campaign_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_domains
    ADD CONSTRAINT campaign_domains_pkey PRIMARY KEY (campaign_id, domain);


--
-- Name: campaign_locations campaign_locations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_locations
    ADD CONSTRAINT campaign_locations_pkey PRIMARY KEY (campaign_id, country_code, region);


--
-- Name: campaigns campaigns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaigns
    ADD CONSTRAINT campaigns_pkey PRIMARY KEY (id);


--
-- Name: camplogs camplogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camplogs
    ADD CONSTRAINT camplogs_pkey PRIMARY KEY (campid, email, cmd);


--
-- Name: campqueue campqueue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campqueue
    ADD CONSTRAINT campqueue_pkey PRIMARY KEY (cid, campid, sendid, domain);


--
-- Name: clientdkim clientdkim_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clientdkim
    ADD CONSTRAINT clientdkim_pkey PRIMARY KEY (id);


--
-- Name: companies companies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (id);


--
-- Name: company_list_group company_list_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_list_group
    ADD CONSTRAINT company_list_group_pkey PRIMARY KEY (parent_cid, cid);


--
-- Name: companylimits companylimits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companylimits
    ADD CONSTRAINT companylimits_pkey PRIMARY KEY (id);


--
-- Name: cookies cookies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cookies
    ADD CONSTRAINT cookies_pkey PRIMARY KEY (id);


--
-- Name: datablocks datablocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datablocks
    ADD CONSTRAINT datablocks_pkey PRIMARY KEY (path);


--
-- Name: dkimentries dkimentries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dkimentries
    ADD CONSTRAINT dkimentries_pkey PRIMARY KEY (id);


--
-- Name: dlq dlq_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dlq
    ADD CONSTRAINT dlq_pkey PRIMARY KEY (id);


--
-- Name: domaingroups domaingroups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domaingroups
    ADD CONSTRAINT domaingroups_pkey PRIMARY KEY (id);


--
-- Name: domainthrottles domainthrottles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.domainthrottles
    ADD CONSTRAINT domainthrottles_pkey PRIMARY KEY (id);


--
-- Name: easylink easylink_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.easylink
    ADD CONSTRAINT easylink_pkey PRIMARY KEY (id);


--
-- Name: eltracking eltracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.eltracking
    ADD CONSTRAINT eltracking_pkey PRIMARY KEY (id);


--
-- Name: exclusions exclusions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exclusions
    ADD CONSTRAINT exclusions_pkey PRIMARY KEY (cid, item, exclusionid);


--
-- Name: exports exports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exports
    ADD CONSTRAINT exports_pkey PRIMARY KEY (id);


--
-- Name: formcookies formcookies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formcookies
    ADD CONSTRAINT formcookies_pkey PRIMARY KEY (formid, uid);


--
-- Name: forms forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forms
    ADD CONSTRAINT forms_pkey PRIMARY KEY (id);


--
-- Name: formtemplates formtemplates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.formtemplates
    ADD CONSTRAINT formtemplates_pkey PRIMARY KEY (id);


--
-- Name: frontends frontends_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.frontends
    ADD CONSTRAINT frontends_pkey PRIMARY KEY (id);


--
-- Name: funnelqueue funnelqueue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.funnelqueue
    ADD CONSTRAINT funnelqueue_pkey PRIMARY KEY (id);


--
-- Name: funnels funnels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.funnels
    ADD CONSTRAINT funnels_pkey PRIMARY KEY (id);


--
-- Name: gallerytemplates gallerytemplates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gallerytemplates
    ADD CONSTRAINT gallerytemplates_pkey PRIMARY KEY (id);


--
-- Name: hourstats_backup hourstats_backup_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hourstats_backup
    ADD CONSTRAINT hourstats_backup_pkey PRIMARY KEY (id);


--
-- Name: hourstats hourstats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hourstats
    ADD CONSTRAINT hourstats_pkey PRIMARY KEY (id);


--
-- Name: hourstats hourstats_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hourstats
    ADD CONSTRAINT hourstats_uniq UNIQUE (ts, sinkid, domaingroupid, ip, settingsid, campid);


--
-- Name: iplimits iplimits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.iplimits
    ADD CONSTRAINT iplimits_pkey PRIMARY KEY (sinkid, settingsid, domain, ip);


--
-- Name: ippauses ippauses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ippauses
    ADD CONSTRAINT ippauses_pkey PRIMARY KEY (id);


--
-- Name: oldlinks links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oldlinks
    ADD CONSTRAINT links_pkey PRIMARY KEY (id);


--
-- Name: list_domains list_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_domains
    ADD CONSTRAINT list_domains_pkey PRIMARY KEY (list_id, domain);


--
-- Name: lists lists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lists
    ADD CONSTRAINT lists_pkey PRIMARY KEY (id);


--
-- Name: locks locks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locks
    ADD CONSTRAINT locks_pkey PRIMARY KEY (name);


--
-- Name: mailgun mailgun_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mailgun
    ADD CONSTRAINT mailgun_pkey PRIMARY KEY (id);


--
-- Name: message_browsers message_browsers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_browsers
    ADD CONSTRAINT message_browsers_pkey PRIMARY KEY (message_id, os, browser);


--
-- Name: message_devices message_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_devices
    ADD CONSTRAINT message_devices_pkey PRIMARY KEY (message_id, device);


--
-- Name: message_domains message_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_domains
    ADD CONSTRAINT message_domains_pkey PRIMARY KEY (message_id, domain);


--
-- Name: message_locations message_locations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_locations
    ADD CONSTRAINT message_locations_pkey PRIMARY KEY (message_id, country_code, region);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: mgtracking mgtracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mgtracking
    ADD CONSTRAINT mgtracking_pkey PRIMARY KEY (id);


--
-- Name: countries new_countries_pkey1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.countries
    ADD CONSTRAINT new_countries_pkey1 PRIMARY KEY (country);


--
-- Name: iplocs new_iplocs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.iplocs
    ADD CONSTRAINT new_iplocs_pkey PRIMARY KEY (id);


--
-- Name: regions new_regions_pkey1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regions
    ADD CONSTRAINT new_regions_pkey1 PRIMARY KEY (country, region);


--
-- Name: links newlinks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.links
    ADD CONSTRAINT newlinks_pkey PRIMARY KEY (id);


--
-- Name: links newlinks_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.links
    ADD CONSTRAINT newlinks_uniq UNIQUE (url, campaign, index, track);


--
-- Name: policies policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT policies_pkey PRIMARY KEY (id);


--
-- Name: resthooks resthooks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resthooks
    ADD CONSTRAINT resthooks_pkey PRIMARY KEY (id);


--
-- Name: routes routes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routes
    ADD CONSTRAINT routes_pkey PRIMARY KEY (id);


--
-- Name: segments segments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.segments
    ADD CONSTRAINT segments_pkey PRIMARY KEY (id);


--
-- Name: sendlimits sendlimits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sendlimits
    ADD CONSTRAINT sendlimits_pkey PRIMARY KEY (id);


--
-- Name: ses ses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ses
    ADD CONSTRAINT ses_pkey PRIMARY KEY (id);


--
-- Name: sesmessages sesmessages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sesmessages
    ADD CONSTRAINT sesmessages_pkey PRIMARY KEY (id);


--
-- Name: sinkdomainqueues sinkdomainqueues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sinkdomainqueues
    ADD CONSTRAINT sinkdomainqueues_pkey PRIMARY KEY (sinkid, domain);


--
-- Name: sinks sinks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sinks
    ADD CONSTRAINT sinks_pkey PRIMARY KEY (id);


--
-- Name: smslinks smslinks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.smslinks
    ADD CONSTRAINT smslinks_pkey PRIMARY KEY (id);


--
-- Name: smtprelays smtprelays_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.smtprelays
    ADD CONSTRAINT smtprelays_pkey PRIMARY KEY (id);


--
-- Name: eltracking smtptracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.smtptracking
    ADD CONSTRAINT smtptracking_pkey PRIMARY KEY (id);


--
-- Name: sparkpost sparkpost_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sparkpost
    ADD CONSTRAINT sparkpost_pkey PRIMARY KEY (id);


--
-- Name: sptracking sptracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sptracking
    ADD CONSTRAINT sptracking_pkey PRIMARY KEY (id);


--
-- Name: statlogs2 statlogs2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statlogs2
    ADD CONSTRAINT statlogs2_pkey PRIMARY KEY (id);


--
-- Name: statlogs_backup statlogs_backup_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statlogs_backup
    ADD CONSTRAINT statlogs_backup_pkey PRIMARY KEY (id);


--
-- Name: statlogs statlogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statlogs
    ADD CONSTRAINT statlogs_pkey PRIMARY KEY (id);


--
-- Name: statmsgs statmsgs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statmsgs
    ADD CONSTRAINT statmsgs_pkey PRIMARY KEY (id);


--
-- Name: statmsgs statmsgs_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.statmsgs
    ADD CONSTRAINT statmsgs_uniq UNIQUE (ts, sinkid, domaingroupid, ip, settingsid, campid, message, msgtype);


--
-- Name: supplists supplists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplists
    ADD CONSTRAINT supplists_pkey PRIMARY KEY (id);


--
-- Name: tableconfigs tableconfigs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tableconfigs
    ADD CONSTRAINT tableconfigs_pkey PRIMARY KEY (id);


--
-- Name: taskgather taskgather_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taskgather
    ADD CONSTRAINT taskgather_pkey PRIMARY KEY (id);


--
-- Name: taskgatherdata taskgatherdata_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taskgatherdata
    ADD CONSTRAINT taskgatherdata_pkey PRIMARY KEY (id);


--
-- Name: templates templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.templates
    ADD CONSTRAINT templates_pkey PRIMARY KEY (id);


--
-- Name: tempusers tempusers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tempusers
    ADD CONSTRAINT tempusers_pkey PRIMARY KEY (id);


--
-- Name: testemails testemails_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.testemails
    ADD CONSTRAINT testemails_pkey PRIMARY KEY (id);


--
-- Name: testlogs testlogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.testlogs
    ADD CONSTRAINT testlogs_pkey PRIMARY KEY (id);


--
-- Name: trumpiamessages trumpiamessages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trumpiamessages
    ADD CONSTRAINT trumpiamessages_pkey PRIMARY KEY (id);


--
-- Name: txnlogs txnlogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txnlogs
    ADD CONSTRAINT txnlogs_pkey PRIMARY KEY (tag, msgid, email, cmd);


--
-- Name: txnqueue txnqueue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txnqueue
    ADD CONSTRAINT txnqueue_pkey PRIMARY KEY (cid, id);


--
-- Name: txnsends txnsends_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txnsends
    ADD CONSTRAINT txnsends_pkey PRIMARY KEY (id);


--
-- Name: txnstatmsgs txnstatmsgs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txnstatmsgs
    ADD CONSTRAINT txnstatmsgs_pkey PRIMARY KEY (id);


--
-- Name: txnstatmsgs txnstatmsgs_ts_cid_tag_domain_message_msgtype_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txnstatmsgs
    ADD CONSTRAINT txnstatmsgs_ts_cid_tag_domain_message_msgtype_key UNIQUE (ts, cid, tag, domain, message, msgtype);


--
-- Name: txnstats txnstats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txnstats
    ADD CONSTRAINT txnstats_pkey PRIMARY KEY (id);


--
-- Name: txnstats txnstats_ts_cid_tag_domain_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txnstats
    ADD CONSTRAINT txnstats_ts_cid_tag_domain_key UNIQUE (ts, cid, tag, domain);


--
-- Name: txntags txntags_cid_tag_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txntags
    ADD CONSTRAINT txntags_cid_tag_key UNIQUE (cid, tag);


--
-- Name: txntags txntags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txntags
    ADD CONSTRAINT txntags_pkey PRIMARY KEY (id);


--
-- Name: txntemplates txntemplates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.txntemplates
    ADD CONSTRAINT txntemplates_pkey PRIMARY KEY (id);


--
-- Name: unsublogs unsublogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unsublogs
    ADD CONSTRAINT unsublogs_pkey PRIMARY KEY (cid, email);


--
-- Name: userlogs userlogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.userlogs
    ADD CONSTRAINT userlogs_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: warmups warmups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warmups
    ADD CONSTRAINT warmups_pkey PRIMARY KEY (id);

--
-- Name: webhooks webhooks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhooks
    ADD CONSTRAINT webhooks_pkey PRIMARY KEY (id);


--
-- Name: apiretries_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX apiretries_cid_idx ON public.apiretries USING btree (cid, queuetype);


--
-- Name: apiretries_retry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX apiretries_retry_idx ON public.apiretries USING btree (retrytime);


--
-- Name: campaigns_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX campaigns_cid_idx ON public.campaigns USING btree (cid);


--
-- Name: campaigns_finished_idx_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX campaigns_finished_idx_2 ON public.campaigns USING btree (((data ->> 'sent_at'::text)), ((data ->> 'finished_at'::text)), ((data ->> 'error'::text)), ((data ->> 'processed_resend'::text)), (((data ->> 'resend'::text))::boolean), ((data ->> 'is_resend'::text)), ((data ->> 'resendwhennum'::text))) WHERE (((data ->> 'sent_at'::text) IS NOT NULL) AND ((data ->> 'finished_at'::text) IS NOT NULL) AND ((data ->> 'error'::text) IS NULL) AND ((data ->> 'processed_resend'::text) IS NULL) AND ((data ->> 'resend'::text))::boolean AND ((data ->> 'is_resend'::text) IS NULL) AND ((data ->> 'resendwhennum'::text) IS NOT NULL));


--
-- Name: campaigns_fromname_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX campaigns_fromname_search ON public.campaigns USING gin (((data ->> 'fromname'::text)) public.gin_trgm_ops);


--
-- Name: campaigns_name_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX campaigns_name_search ON public.campaigns USING gin (((data ->> 'name'::text)) public.gin_trgm_ops);


--
-- Name: campaigns_scheduled_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX campaigns_scheduled_idx ON public.campaigns USING btree (((data ->> 'when'::text)), ((data ->> 'scheduled_for'::text)), ((data ->> 'sent_at'::text)), ((data ->> 'processed_schedule'::text)), ((data ->> 'scheduled_for'::text)));


--
-- Name: campaigns_sent_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX campaigns_sent_at_idx ON public.campaigns USING btree (cid, ((data ->> 'sent_at'::text)));


--
-- Name: campaigns_sent_at_idx_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX campaigns_sent_at_idx_2 ON public.campaigns USING btree (cid, ((data ->> 'sent_at'::text))) WHERE ((data ->> 'sent_at'::text) IS NOT NULL);


--
-- Name: campaigns_subject_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX campaigns_subject_search ON public.campaigns USING gin (((data ->> 'subject'::text)) public.gin_trgm_ops);


--
-- Name: clientdkim_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX clientdkim_cid_idx ON public.clientdkim USING btree (cid);


--
-- Name: companies_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX companies_cid_idx ON public.companies USING btree (cid);


--
-- Name: companylimits_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX companylimits_cid_idx ON public.companylimits USING btree (cid);


--
-- Name: cookies_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cookies_cid_idx ON public.cookies USING btree (cid);


--
-- Name: dkimentries_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dkimentries_cid_idx ON public.dkimentries USING btree (cid);


--
-- Name: dlq_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dlq_cid_idx ON public.dlq USING btree (cid);


--
-- Name: domaingroups_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX domaingroups_cid_idx ON public.domaingroups USING btree (cid);


--
-- Name: domainthrottles_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX domainthrottles_cid_idx ON public.domainthrottles USING btree (cid);


--
-- Name: easylink_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX easylink_cid_idx ON public.easylink USING btree (cid);


--
-- Name: exports_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX exports_cid_idx ON public.exports USING btree (cid);


--
-- Name: forms_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX forms_cid_idx ON public.forms USING btree (cid);


--
-- Name: formtemplates_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX formtemplates_cid_idx ON public.formtemplates USING btree (cid);


--
-- Name: frontends_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX frontends_cid_idx ON public.frontends USING btree (cid);


--
-- Name: funnelqueue_sent_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX funnelqueue_sent_idx ON public.funnelqueue USING btree (sent, messageid);


--
-- Name: funnelqueue_uniq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX funnelqueue_uniq_idx ON public.funnelqueue USING btree (email, messageid);


--
-- Name: funnels_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX funnels_cid_idx ON public.funnels USING btree (cid);


--
-- Name: gallerytemplates_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gallerytemplates_cid_idx ON public.gallerytemplates USING btree (cid);


--
-- Name: hourstats_campcid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX hourstats_campcid_idx ON public.hourstats USING btree (campcid, ts);


--
-- Name: hourstats_campid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX hourstats_campid_idx ON public.hourstats USING btree (campid);


--
-- Name: hourstats_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX hourstats_cid_idx ON public.hourstats USING btree (cid);


--
-- Name: hourstats_ts_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX hourstats_ts_cid_idx ON public.hourstats USING btree (ts, cid, sinkid, send, soft, hard, err, open, defercnt);


--
-- Name: ipcities_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ipcities_idx ON public.ipcities USING gist (iprange);


--
-- Name: iplocations_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX iplocations_idx ON public.iplocations USING gist (iprange);


--
-- Name: ippauses_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ippauses_cid_idx ON public.ippauses USING btree (cid);


--
-- Name: ippauses_uniq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ippauses_uniq_idx ON public.ippauses USING btree (((data ->> 'domaingroupid'::text)), ((data ->> 'ip'::text)), ((data ->> 'settingsid'::text)), ((data ->> 'sinkid'::text)));


--
-- Name: links_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX links_cid_idx ON public.oldlinks USING btree (cid);


--
-- Name: lists_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX lists_cid_idx ON public.lists USING btree (cid);


--
-- Name: mailgun_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX mailgun_cid_idx ON public.mailgun USING btree (cid);


--
-- Name: messages_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX messages_cid_idx ON public.messages USING btree (cid);


--
-- Name: policies_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX policies_cid_idx ON public.policies USING btree (cid);


--
-- Name: resthooks_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX resthooks_cid_idx ON public.resthooks USING btree (cid);


--
-- Name: routes_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX routes_cid_idx ON public.routes USING btree (cid);


--
-- Name: segments_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX segments_cid_idx ON public.segments USING btree (cid);


--
-- Name: sendlimits_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sendlimits_cid_idx ON public.sendlimits USING btree (cid);


--
-- Name: ses_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ses_cid_idx ON public.ses USING btree (cid);


--
-- Name: sesmessages_trackingid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sesmessages_trackingid_idx ON public.sesmessages USING btree (trackingid);


--
-- Name: sinks_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sinks_cid_idx ON public.sinks USING btree (cid);


--
-- Name: smtprelays_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX smtprelays_cid_idx ON public.smtprelays USING btree (cid);


--
-- Name: sparkpost_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sparkpost_cid_idx ON public.sparkpost USING btree (cid);


--
-- Name: statlogs2_cid_domaingroupid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX statlogs2_cid_domaingroupid_idx ON public.statlogs2 USING btree (cid, sinkid, ip, settingsid, domaingroupid, ts) WHERE (domaingroupid <> ''::text);


--
-- Name: statlogs2_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX statlogs2_cid_idx ON public.statlogs2 USING btree (cid);


--
-- Name: statlogs2_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX statlogs2_idx ON public.statlogs2 USING btree (cid, ip, settingsid, domaingroupid, sinkid, ts);


--
-- Name: statlogs_cid_domaingroupid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX statlogs_cid_domaingroupid_idx ON public.statlogs USING btree (cid, ((data ->> 'sinkid'::text)), ((data ->> 'ip'::text)), ((data ->> 'settingsid'::text)), ((data ->> 'domaingroupid'::text)), ((data -> 'ts'::text))) WHERE ((data ->> 'domaingroupid'::text) <> ''::text);


--
-- Name: statlogs_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX statlogs_cid_idx ON public.statlogs USING btree (cid);


--
-- Name: statlogs_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX statlogs_gin ON public.statlogs USING gin (cid, data);


--
-- Name: statlogs_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX statlogs_idx ON public.statlogs USING btree (cid, ((data ->> 'ip'::text)), ((data ->> 'settingsid'::text)), ((data ->> 'domaingroupid'::text)), ((data ->> 'sinkid'::text)), ((data ->> 'ts'::text)));


--
-- Name: statmsgs_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX statmsgs_cid_idx ON public.statmsgs USING btree (cid);


--
-- Name: supplists_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX supplists_cid_idx ON public.supplists USING btree (cid);


--
-- Name: tableconfigs_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tableconfigs_cid_idx ON public.tableconfigs USING btree (cid);


--
-- Name: taskgather_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX taskgather_cid_idx ON public.taskgather USING btree (cid);


--
-- Name: taskgatherdata_gatherid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX taskgatherdata_gatherid_idx ON public.taskgatherdata USING btree (((data ->> 'gatherid'::text)));


--
-- Name: templates_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX templates_cid_idx ON public.templates USING btree (cid);


--
-- Name: tempusers_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tempusers_cid_idx ON public.tempusers USING btree (cid);


--
-- Name: tempusers_username_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tempusers_username_idx ON public.tempusers USING btree (((data ->> 'username'::text)));


--
-- Name: testlogs_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX testlogs_cid_idx ON public.testlogs USING btree (cid);


--
-- Name: trumpiamessages_trackingid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trumpiamessages_trackingid_idx ON public.trumpiamessages USING btree (trackingid);


--
-- Name: txnsends_cid_ts_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX txnsends_cid_ts_index ON public.txnsends USING btree (cid, ts);


--
-- Name: txnsends_ts_index; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX txnsends_ts_index ON public.txnsends USING btree (ts);


--
-- Name: txnstatmsgs_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX txnstatmsgs_cid_idx ON public.txnstatmsgs USING btree (cid);


--
-- Name: txnstats_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX txnstats_cid_idx ON public.txnstats USING btree (cid);


--
-- Name: txntemplates_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX txntemplates_cid_idx ON public.txntemplates USING btree (cid);


--
-- Name: userlogs_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX userlogs_cid_idx ON public.userlogs USING btree (cid);


--
-- Name: users_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_cid_idx ON public.users USING btree (cid);


--
-- Name: users_username_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_username_idx ON public.users USING btree (((data ->> 'username'::text)));


--
-- Name: warmups_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX warmups_cid_idx ON public.warmups USING btree (cid);

--
-- Name: webhooks_cid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX webhooks_cid_idx ON public.webhooks USING btree (cid);


--
-- Name: statlogs2_stats; Type: STATISTICS; Schema: public; Owner: -
--

CREATE STATISTICS public.statlogs2_stats (ndistinct) ON ip, sinkid, settingsid, domaingroupid FROM public.statlogs2;


--
-- Name: campaign_browsers campaign_browsers_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_browsers
    ADD CONSTRAINT campaign_browsers_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: campaign_devices campaign_devices_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_devices
    ADD CONSTRAINT campaign_devices_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: campaign_domains campaign_domains_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_domains
    ADD CONSTRAINT campaign_domains_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: campaign_locations campaign_locations_campaign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_locations
    ADD CONSTRAINT campaign_locations_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.campaigns(id) ON DELETE CASCADE;


--
-- Name: list_domains list_domains_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_domains
    ADD CONSTRAINT list_domains_list_id_fkey FOREIGN KEY (list_id) REFERENCES public.lists(id) ON DELETE CASCADE;


--
-- Name: message_browsers message_browsers_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_browsers
    ADD CONSTRAINT message_browsers_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE;


--
-- Name: message_devices message_devices_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_devices
    ADD CONSTRAINT message_devices_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE;


--
-- Name: message_domains message_domains_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_domains
    ADD CONSTRAINT message_domains_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE;


--
-- Name: message_locations message_locations_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_locations
    ADD CONSTRAINT message_locations_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE;


--
-- Name: sinkdomainqueues sinkdomainqueues_sinkid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sinkdomainqueues
    ADD CONSTRAINT sinkdomainqueues_sinkid_fkey FOREIGN KEY (sinkid) REFERENCES public.sinks(id) ON DELETE CASCADE;




--
-- PostgreSQL database dump complete
--

-- Automation tables, including subject experiments, are created in dependency
-- order by scripts/run_db_migrations.py after this base schema is imported.
