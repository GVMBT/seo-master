# Modular routers/ -- Aiogram Handlers

## Structure

### Top-level
| File | LOC | Purpose |
|---|---|---|
| start.py | 691 | /start, /cancel, Dashboard, pipeline resume |
| oauth_deeplinks.py | 410 | Pinterest OAuth callback, VK OAuth callback, `_return_to_pipeline()` |
| profile.py | 349 | profile, notifications, referral, /privacy, /terms, /delete_account |
| tariffs.py | 161 | token packages, payment method selection |
| payments.py | 158 | pre_checkout_query, successful_payment (Stars + YooKassa) |

### routers/projects/
| File | LOC | Purpose |
|---|---|---|
| list.py | 89 | project list, pagination |
| card.py | 202 | project card, delete confirm |
| create.py | 457 | ProjectCreateFSM (name, url, description, branding) |
| _settings_common.py | 317 | content settings helpers, main settings screen |
| text_settings.py | 288 | 7 text option handlers (psettings:text:* callbacks) |
| image_settings.py | 741 | 19 image option handlers (psettings:image:* callbacks) |
| content_settings.py | 17 | Backward-compatible re-exports (facade) |

### routers/categories/
| File | LOC | Purpose |
|---|---|---|
| manage.py | 408 | category list, card, create (CategoryCreateFSM), delete |
| keywords.py | 885 | keyword generation, upload, clusters, download, delete |
| description.py | 507 | DescriptionGenerateFSM (AI generate, manual input, review) |
| prices.py | 510 | PriceInputFSM (text input, Excel upload, delete) |

### routers/platforms/
| File | LOC | Purpose |
|---|---|---|
| _shared.py | 461 | Shared constants, helpers, CRUD handlers (list, manage, delete) |
| wordpress.py | 243 | ConnectWordPressFSM wizard (3 states: url, login, password) |
| telegram.py | 388 | ConnectTelegramFSM wizard (3 states: channel, token, topic) |
| vk.py | 462 | ConnectVKFSM wizard (3 states: select_type, enter_group_url, enter_token) |
| pinterest.py | 108 | ConnectPinterestFSM wizard (OAuth flow) |
| connections.py | 18 | Backward-compatible re-exports (facade) |

### routers/publishing/
| File | LOC | Purpose |
|---|---|---|
| scheduler.py | 1011 | ScheduleSetupFSM -- article + social scheduling, presets, crosspost config |

### routers/publishing/pipeline/
| File | LOC | Purpose |
|---|---|---|
| article.py | 1130 | ArticlePipelineFSM -- article funnel (project, category, WP, confirm) |
| generation.py | 1215 | article generation (multi-step AI), preview, publish, regenerate |
| readiness.py | 583 | readiness check inline sub-flows (keywords, description, images) |
| _common.py | 267 | shared pipeline helpers (safe_message, checkpoint, error handling) |
| _readiness_common.py | 669 | shared readiness logic (ReadinessService integration) |
| exit_protection.py | 143 | exit confirmation dialog |

### routers/publishing/pipeline/social/
| File | LOC | Purpose |
|---|---|---|
| social.py | 704 | SocialPipelineFSM (project, category, connection) |
| connection.py | 1238 | inline connection wizard within social pipeline (WP, TG, VK, Pinterest) |
| generation.py | 983 | social post generation, review, publish |
| crosspost.py | 330 | cross-post flow: select, toggle, execute (F6.4) |
| readiness.py | 273 | readiness check for social pipeline |

### routers/shared/
| File | LOC | Purpose |
|---|---|---|
| keyword_wizard.py | 832 | reusable KeywordWizardFSM (used by categories + pipeline readiness) |

### routers/admin/
| File | LOC | Purpose |
|---|---|---|
| dashboard.py | ~670 | admin panel, user lookup, broadcast, API status, portals |
| costs.py | ~235 | real API costs from OpenRouter Activity + external balances |

## callback_data prefix -> file
| Prefix | File(s) |
|---|---|
| `nav:*` | start.py |
| `legal:*` | start.py (consent) |
| `project:*` | projects/ (list, card, create), content_settings, scheduler |
| `psettings:*` | projects/content_settings.py (_settings_common, text_settings, image_settings) |
| `page:projects:*` | projects/list.py |
| `category:*` | categories/ (manage, keywords, description, prices) |
| `page:categories:*` | categories/manage.py |
| `kw:*` | categories/keywords.py |
| `page:clusters:*`, `page:del_clusters:*` | categories/keywords.py |
| `desc:*` | categories/description.py |
| `prices:*`, `price:*` | categories/prices.py |
| `conn:*` | platforms/_shared.py |
| `scheduler:*`, `sched:*`, `sched_social:*`, `sched_xp:*` | publishing/scheduler.py |
| `pipeline:article:*` | publishing/pipeline/article.py, generation.py |
| `pipeline:readiness:*` | publishing/pipeline/readiness.py |
| `pipeline:social:*` | publishing/pipeline/social/ |
| `pipeline:crosspost:*` | publishing/pipeline/social/crosspost.py |
| `pipeline:cancel`, `pipeline:resume`, `pipeline:restart` | start.py |
| `profile:*`, `account:*` | profile.py |
| `tariff:*` | tariffs.py |
| `admin:*`, `broadcast:*` | admin/dashboard.py (panel, api_status, api_costs, portals, user_lookup, broadcast) |
| `fsm:cancel` | shared cancel handler (keyboards/common.py cancel_kb) |
| `noop` | no-op answer (various) |
