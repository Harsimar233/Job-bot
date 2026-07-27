-- Super Job Bot database schema
-- Run once in Supabase SQL Editor.

create table if not exists public.users (
  chat_id bigint primary key,
  username text default '',
  active boolean not null default false,
  setup_complete boolean not null default false,
  category text not null default 'all',
  seniority text not null default 'all',
  keywords text not null default '',
  location text not null default 'Worldwide',
  location_key text not null default 'worldwide',
  remote_only boolean not null default false,
  work_mode text not null default 'any',
  relocation_only boolean not null default false,
  target_countries text not null default '',
  company_type text not null default 'any',
  awaiting_keywords boolean not null default false,
  awaiting_search boolean not null default false,
  awaiting_abroad_countries boolean not null default false,
  awaiting_role boolean not null default false,
  awaiting_seniority boolean not null default false,
  awaiting_location boolean not null default false,
  awaiting_custom_location boolean not null default false,
  awaiting_ctype boolean not null default false,
  streak integer not null default 0,
  referrals integer not null default 0,
  referred_by bigint,
  last_find_at timestamptz,
  last_alert_date timestamptz,
  last_active_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.jobs (
  job_id text primary key,
  title text not null,
  company text not null default '',
  url text not null,
  source text not null default '',
  date_posted text default '',
  location text not null default 'Remote',
  description text default '',
  salary text default '',
  funding text default '',
  company_type text default '',
  work_mode text not null default 'unknown',
  employment_type text not null default 'unknown',
  category text default '',
  experience text default '',
  apply_method text not null default 'url',
  discovery_method text not null default 'scraper',
  evidence text default '',
  visa_status text not null default 'unknown'
    check (visa_status in ('confirmed', 'possible', 'not_offered', 'unknown')),
  overseas_candidates boolean not null default false,
  visa boolean not null default false,
  hot boolean not null default false,
  scraped_at timestamptz not null default now()
);

create table if not exists public.sent_jobs (
  id bigint generated always as identity primary key,
  chat_id bigint not null references public.users(chat_id) on delete cascade,
  job_id text not null,
  sent_at timestamptz not null default now(),
  unique (chat_id, job_id)
);

create table if not exists public.saved_jobs (
  id bigint generated always as identity primary key,
  chat_id bigint not null references public.users(chat_id) on delete cascade,
  job_id text not null,
  job_title text not null default '',
  company text not null default '',
  url text not null default '',
  source text not null default '',
  created_at timestamptz not null default now(),
  unique (chat_id, job_id)
);

create table if not exists public.job_feedback (
  id bigint generated always as identity primary key,
  chat_id bigint not null references public.users(chat_id) on delete cascade,
  job_id text not null,
  feedback text not null check (feedback in ('like', 'dislike')),
  created_at timestamptz not null default now(),
  unique (chat_id, job_id)
);

create table if not exists public.watchlist (
  id bigint generated always as identity primary key,
  chat_id bigint not null references public.users(chat_id) on delete cascade,
  company text not null,
  created_at timestamptz not null default now(),
  unique (chat_id, company)
);

create table if not exists public.analytics (
  id bigint generated always as identity primary key,
  chat_id bigint references public.users(chat_id) on delete cascade,
  event text not null,
  meta jsonb not null default '{}'::jsonb,
  ts timestamptz not null default now()
);

create table if not exists public.candidate_profiles (
  chat_id bigint primary key references public.users(chat_id) on delete cascade,
  auto_apply_mode text not null default 'off'
    check (auto_apply_mode in ('off', 'review')),
  setup_step text not null default 'not_started'
    check (setup_step in (
      'not_started', 'awaiting_resume', 'awaiting_name', 'awaiting_email',
      'awaiting_phone', 'awaiting_city', 'ready'
    )),
  resume_file_id text,
  resume_file_unique_id text,
  resume_file_name text,
  resume_mime_type text,
  resume_size bigint,
  full_name text not null default '',
  email text not null default '',
  phone text not null default '',
  current_city text not null default '',
  consent_version text,
  consented_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.applications (
  id bigint generated always as identity primary key,
  chat_id bigint not null references public.users(chat_id) on delete cascade,
  job_id text not null,
  status text not null default 'queued'
    check (status in (
      'queued', 'awaiting_approval', 'approved', 'manual_required',
      'submitted', 'failed', 'skipped'
    )),
  adapter text not null default 'generic_web',
  apply_method text not null default 'review_then_open',
  cover_letter text not null default '',
  why_fit text not null default '',
  questions_to_confirm jsonb not null default '[]'::jsonb,
  job_snapshot jsonb not null default '{}'::jsonb,
  approved_at timestamptz,
  submitted_at timestamptz,
  failure_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (chat_id, job_id)
);

create index if not exists jobs_scraped_at_idx on public.jobs (scraped_at desc);
create index if not exists jobs_location_idx on public.jobs (location);
create index if not exists jobs_category_idx on public.jobs (category);
create index if not exists sent_jobs_chat_idx on public.sent_jobs (chat_id);
create index if not exists feedback_chat_idx on public.job_feedback (chat_id);
create index if not exists watchlist_chat_idx on public.watchlist (chat_id);
create index if not exists applications_chat_status_idx
  on public.applications (chat_id, status, created_at desc);

-- Safe upgrades for databases created with an earlier Super Job Bot schema.
alter table public.users add column if not exists relocation_only boolean not null default false;
alter table public.users add column if not exists target_countries text not null default '';
alter table public.users add column if not exists awaiting_abroad_countries boolean not null default false;
alter table public.jobs add column if not exists description text default '';
alter table public.jobs add column if not exists visa_status text not null default 'unknown';
alter table public.jobs add column if not exists overseas_candidates boolean not null default false;

-- The bot uses the service_role key from server-side functions. Keep these
-- tables inaccessible to browser clients unless you later add explicit policies.
alter table public.users enable row level security;
alter table public.jobs enable row level security;
alter table public.sent_jobs enable row level security;
alter table public.saved_jobs enable row level security;
alter table public.job_feedback enable row level security;
alter table public.watchlist enable row level security;
alter table public.analytics enable row level security;
alter table public.candidate_profiles enable row level security;
alter table public.applications enable row level security;
