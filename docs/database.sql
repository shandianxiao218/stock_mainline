-- A股板块主线雷达 PostgreSQL DDL draft
-- 此文件为长期 PostgreSQL 迁移草案，当前以 SQLite 为准，不随实现同步更新。

create table if not exists trading_calendar (
  trade_date date primary key,
  is_open boolean not null,
  previous_trade_date date,
  next_trade_date date,
  source varchar(64) not null,
  created_at timestamp not null default current_timestamp
);

create table if not exists stock_daily_quote (
  id bigserial primary key,
  trade_date date not null,
  ts_code varchar(16) not null,
  name varchar(64),
  open numeric(12,4),
  high numeric(12,4),
  low numeric(12,4),
  close numeric(12,4),
  pct_chg numeric(10,4),
  amount numeric(20,4),
  vol numeric(20,4),
  turnover_rate numeric(10,4),
  circ_mv numeric(20,4),
  source varchar(64) not null,
  collected_at timestamp not null default current_timestamp,
  unique (trade_date, ts_code, source)
);

create table if not exists sector_definition (
  sector_id varchar(64) primary key,
  sector_name varchar(128) not null,
  sector_type varchar(32) not null,
  source varchar(64) not null,
  is_active boolean not null default true,
  created_at timestamp not null default current_timestamp
);

create table if not exists sector_constituent_history (
  id bigserial primary key,
  sector_id varchar(64) not null references sector_definition(sector_id),
  ts_code varchar(16) not null,
  weight numeric(10,4),
  start_date date not null,
  end_date date,
  source varchar(64) not null,
  created_at timestamp not null default current_timestamp
);

create index if not exists idx_sector_constituent_date
  on sector_constituent_history (sector_id, start_date, end_date);

create table if not exists theme_definition (
  theme_id varchar(64) primary key,
  theme_name varchar(128) not null,
  definition_version varchar(32) not null,
  aggregation_method varchar(32) not null,
  status varchar(32) not null default 'active',
  created_by varchar(64) not null default 'system',
  created_at timestamp not null default current_timestamp
);

create table if not exists theme_sector_mapping (
  id bigserial primary key,
  theme_id varchar(64) not null references theme_definition(theme_id),
  sector_id varchar(64) not null references sector_definition(sector_id),
  mapping_score numeric(10,4),
  definition_version varchar(32) not null,
  start_date date not null,
  end_date date
);

create table if not exists stock_theme_mapping (
  id bigserial primary key,
  trade_date date not null,
  theme_id varchar(64) not null references theme_definition(theme_id),
  ts_code varchar(16) not null,
  role varchar(32) not null,
  score numeric(10,4),
  unique (trade_date, theme_id, ts_code, role)
);

create table if not exists limit_up_daily (
  id bigserial primary key,
  trade_date date not null,
  ts_code varchar(16) not null,
  limit_type varchar(16) not null,
  touched_limit boolean not null default false,
  sealed_limit boolean not null default false,
  broke_limit boolean not null default false,
  consecutive_boards int,
  seal_amount numeric(20,4),
  source varchar(64) not null,
  unique (trade_date, ts_code, source)
);

create table if not exists sentiment_daily (
  id bigserial primary key,
  trade_date date not null,
  object_type varchar(16) not null,
  object_id varchar(64) not null,
  sentiment_heat numeric(10,4),
  sentiment_momentum numeric(10,4),
  keyword_json jsonb,
  source varchar(64) not null,
  created_at timestamp not null default current_timestamp,
  unique (trade_date, object_type, object_id, source)
);

create table if not exists catalyst_event (
  id bigserial primary key,
  event_date date not null,
  theme_id varchar(64),
  sector_id varchar(64),
  title varchar(256) not null,
  catalyst_level varchar(8) not null,
  score numeric(10,4) not null,
  source varchar(128),
  manual_corrected boolean not null default false,
  created_at timestamp not null default current_timestamp
);

create table if not exists model_version (
  model_version varchar(32) primary key,
  description text,
  created_at timestamp not null default current_timestamp
);

create table if not exists model_config (
  config_id bigserial primary key,
  model_version varchar(32) not null references model_version(model_version),
  config_version varchar(32) not null,
  config_json jsonb not null,
  created_by varchar(64) not null,
  created_at timestamp not null default current_timestamp,
  unique (model_version, config_version)
);

create table if not exists sector_score_daily (
  id bigserial primary key,
  trade_date date not null,
  sector_id varchar(64) not null references sector_definition(sector_id),
  model_version varchar(32) not null,
  heat_score numeric(10,4) not null,
  continuation_score numeric(10,4) not null,
  risk_penalty numeric(10,4) not null,
  composite_score numeric(10,4) not null,
  factor_json jsonb not null,
  created_at timestamp not null default current_timestamp,
  unique (trade_date, sector_id, model_version)
);

create table if not exists theme_score_daily (
  id bigserial primary key,
  trade_date date not null,
  theme_id varchar(64) not null references theme_definition(theme_id),
  model_version varchar(32) not null,
  heat_score numeric(10,4) not null,
  continuation_score numeric(10,4) not null,
  risk_penalty numeric(10,4) not null,
  theme_score numeric(10,4) not null,
  rank int not null,
  confidence_level varchar(32) not null,
  status varchar(64) not null,
  explanation_json jsonb not null,
  created_at timestamp not null default current_timestamp,
  unique (trade_date, theme_id, model_version)
);

create index if not exists idx_theme_score_rank
  on theme_score_daily (trade_date, model_version, rank);

create table if not exists risk_signal_daily (
  id bigserial primary key,
  trade_date date not null,
  object_type varchar(16) not null,
  object_id varchar(64) not null,
  risk_type varchar(64) not null,
  penalty numeric(10,4) not null,
  severity varchar(16) not null,
  trigger_reason text not null,
  raw_metric_json jsonb,
  created_at timestamp not null default current_timestamp
);

create table if not exists confidence_daily (
  id bigserial primary key,
  trade_date date not null,
  model_version varchar(32) not null,
  confidence_score numeric(10,4) not null,
  confidence_level varchar(16) not null,
  component_json jsonb not null,
  reason text not null,
  created_at timestamp not null default current_timestamp,
  unique (trade_date, model_version)
);

create table if not exists watchlist_stock (
  id bigserial primary key,
  ts_code varchar(16) not null,
  name varchar(64) not null,
  tag varchar(64),
  created_at timestamp not null default current_timestamp,
  unique (ts_code)
);

create table if not exists portfolio_position (
  id bigserial primary key,
  ts_code varchar(16) not null,
  name varchar(64) not null,
  quantity numeric(20,4) not null,
  cost_price numeric(12,4),
  tag varchar(64),
  created_at timestamp not null default current_timestamp,
  updated_at timestamp not null default current_timestamp,
  unique (ts_code)
);

create table if not exists backtest_result (
  id bigserial primary key,
  task_id varchar(64) not null,
  start_date date not null,
  end_date date not null,
  model_version varchar(32) not null,
  holding_period int not null,
  top_n int not null,
  metrics_json jsonb not null,
  created_at timestamp not null default current_timestamp
);
