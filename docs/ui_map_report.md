# UI Map Report — SEO Master Bot

Auto-generated from AST analysis.

## 1. FSM StatesGroup Classes

Total: **17** FSM groups

### BroadcastFSM
File: `routers/admin/broadcast.py:29`

States (2):
  1. `text`
  2. `confirm`

### CompetitorAnalysisFSM
File: `routers/analysis.py:51`

States (4):
  1. `url`
  2. `confirm`
  3. `analyzing`
  4. `results`

### DescriptionGenerateFSM
File: `routers/categories/description.py:34`

States (2):
  1. `confirm`
  2. `review`

### KeywordGenerationFSM
File: `routers/categories/keywords.py:42`

States (8):
  1. `products`
  2. `geography`
  3. `quantity`
  4. `confirm`
  5. `fetching`
  6. `clustering`
  7. `enriching`
  8. `results`

### KeywordUploadFSM
File: `routers/categories/keywords.py:53`

States (4):
  1. `file_upload`
  2. `enriching`
  3. `clustering`
  4. `results`

### CategoryCreateFSM
File: `routers/categories/manage.py:33`

States (1):
  1. `name`

### PriceInputFSM
File: `routers/categories/prices.py:35`

States (3):
  1. `choose_method`
  2. `text_input`
  3. `file_upload`

### ReviewGenerationFSM
File: `routers/categories/reviews.py:34`

States (4):
  1. `quantity`
  2. `confirm_cost`
  3. `generating`
  4. `review`

### ConnectWordPressFSM
File: `routers/platforms/connections.py:43`

States (3):
  1. `url`
  2. `login`
  3. `password`

### ConnectTelegramFSM
File: `routers/platforms/connections.py:49`

States (2):
  1. `channel`
  2. `token`

### ConnectVKFSM
File: `routers/platforms/connections.py:54`

States (2):
  1. `token`
  2. `select_group`

### ConnectPinterestFSM
File: `routers/platforms/connections.py:59`

States (2):
  1. `oauth_callback`
  2. `select_board`

### ProjectCreateFSM
File: `routers/projects/create.py:32`

States (4):
  1. `name`
  2. `company_name`
  3. `specialization`
  4. `website_url`

### ProjectEditFSM
File: `routers/projects/create.py:39`

States (1):
  1. `field_value`

### ArticlePublishFSM
File: `routers/publishing/preview.py:66`

States (5):
  1. `confirm_cost`
  2. `generating`
  3. `preview`
  4. `publishing`
  5. `regenerating`

### ScheduleSetupFSM
File: `routers/publishing/scheduler.py:44`

States (3):
  1. `select_days`
  2. `select_count`
  3. `select_times`

### SocialPostPublishFSM
File: `routers/publishing/social.py:46`

States (5):
  1. `confirm_cost`
  2. `generating`
  3. `review`
  4. `publishing`
  5. `regenerating`

## 2. Handlers

Total: **160** handlers
  - callback_query: 126
  - message: 34

### routers/admin/broadcast.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_broadcast_start` | callback_query | `-` | `F.data == 'admin:broadcast'` | - |
| `cb_broadcast_audience` | callback_query | `-` | `F.data.regexp('^admin:bc:(all|active_7d|active_...` | BroadcastFSM.text |
| `fsm_broadcast_text` | message | `BroadcastFSM.text` | `-` | BroadcastFSM.confirm, CLEAR |
| `cb_broadcast_confirm` | callback_query | `BroadcastFSM.confirm` | `F.data == 'admin:bc:confirm'` | CLEAR |

### routers/admin/dashboard.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `btn_admin_main` | message | `-` | `-` | - |
| `cb_admin_main` | callback_query | `-` | `F.data == 'admin:main'` | - |
| `cb_admin_monitoring` | callback_query | `-` | `F.data == 'admin:monitoring'` | - |
| `cb_admin_costs` | callback_query | `-` | `F.data == 'admin:costs'` | - |

### routers/analysis.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_project_audit` | callback_query | `-` | `F.data.regexp('^project:(\\d+):audit$')` | - |
| `cb_audit_run` | callback_query | `-` | `F.data.regexp('^project:(\\d+):audit:run$')` | - |
| `cb_competitor_start` | callback_query | `-` | `F.data.regexp('^project:(\\d+):competitor$')` | CompetitorAnalysisFSM.url |
| `fsm_competitor_url` | message | `CompetitorAnalysisFSM.url` | `-` | CompetitorAnalysisFSM.confirm |
| `cb_competitor_confirm` | callback_query | `CompetitorAnalysisFSM.confirm` | `F.data == 'comp:confirm'` | CompetitorAnalysisFSM.analyzing, CLEAR |

### routers/categories/description.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_description_start` | callback_query | `-` | `F.data.regexp('^category:(\\d+):description$')` | DescriptionGenerateFSM.confirm |
| `cb_description_regen_entry` | callback_query | `-` | `F.data.regexp('^category:(\\d+):description:reg...` | DescriptionGenerateFSM.confirm |
| `cb_description_confirm` | callback_query | `DescriptionGenerateFSM.confirm` | `F.data == 'desc:confirm'` | DescriptionGenerateFSM.review, CLEAR |
| `cb_description_save` | callback_query | `DescriptionGenerateFSM.review` | `F.data == 'desc:save'` | CLEAR |
| `cb_description_regen` | callback_query | `DescriptionGenerateFSM.review` | `F.data == 'desc:regen'` | CLEAR |

### routers/categories/keywords.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_keywords_main` | callback_query | `-` | `F.data.regexp('^category:(\\d+):keywords$')` | - |
| `cb_kw_generate_start` | callback_query | `-` | `F.data.regexp('^category:(\\d+):kw:generate$')` | KeywordGenerationFSM.products |
| `fsm_kw_products` | message | `KeywordGenerationFSM.products` | `-` | KeywordGenerationFSM.geography |
| `fsm_kw_geography` | message | `KeywordGenerationFSM.geography` | `-` | KeywordGenerationFSM.quantity |
| `cb_kw_quantity` | callback_query | `KeywordGenerationFSM.quantity` | `F.data.regexp('^kw:qty:(\\d+):(\\d+)$')` | KeywordGenerationFSM.confirm |
| `cb_kw_confirm` | callback_query | `KeywordGenerationFSM.confirm` | `F.data == 'kw:confirm'` | KeywordGenerationFSM.fetching, KeywordGenerationFSM.clustering, KeywordGenerationFSM.enriching, KeywordGenerationFSM.results |
| `cb_kw_save` | callback_query | `KeywordGenerationFSM.results` | `F.data == 'kw:save'` | CLEAR |
| `cb_kw_results_cancel` | callback_query | `KeywordGenerationFSM.results` | `F.data == 'kw:results:cancel'` | CLEAR |
| `cb_kw_upload_start` | callback_query | `-` | `F.data.regexp('^category:(\\d+):kw:upload$')` | KeywordUploadFSM.file_upload |
| `fsm_kw_upload_file` | message | `KeywordUploadFSM.file_upload` | `-` | KeywordUploadFSM.enriching, KeywordUploadFSM.clustering, KeywordUploadFSM.results |
| `cb_kw_upload_save` | callback_query | `KeywordUploadFSM.results` | `F.data == 'kw:save'` | CLEAR |
| `cb_kw_upload_results_cancel` | callback_query | `KeywordUploadFSM.results` | `F.data == 'kw:results:cancel'` | CLEAR |
| `cb_kw_pipeline_guard` | callback_query | `-` | `-` | - |
| `cb_kw_upload_pipeline_guard` | callback_query | `-` | `-` | - |

### routers/categories/manage.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_category_list` | callback_query | `-` | `F.data.regexp('^project:(\\d+):categories$')` | - |
| `cb_category_page` | callback_query | `-` | `F.data.regexp('^page:categories:(\\d+):(\\d+)$')` | - |
| `cb_category_card` | callback_query | `-` | `F.data.regexp('^category:(\\d+):card$')` | - |
| `cb_category_feature_stub` | callback_query | `-` | `F.data.regexp('^category:(\\d+):(img_settings|t...` | - |
| `cb_category_new` | callback_query | `-` | `F.data.regexp('^project:(\\d+):cat:new$')` | CategoryCreateFSM.name |
| `fsm_category_name` | message | `CategoryCreateFSM.name` | `-` | CLEAR |
| `cb_category_delete` | callback_query | `-` | `F.data.regexp('^category:(\\d+):delete$')` | - |
| `cb_category_delete_confirm` | callback_query | `-` | `F.data.regexp('^category:(\\d+):delete:confirm$')` | - |

### routers/categories/media.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_media_start` | callback_query | `-` | `F.data.regexp('^category:(\\d+):media$')` | - |
| `cb_media_upload_prompt` | callback_query | `-` | `F.data.regexp('^media:cat:(\\d+):upload$')` | - |
| `on_photo_received` | message | `-` | `-` | - |
| `on_document_received` | message | `-` | `-` | - |
| `cb_media_clear` | callback_query | `-` | `F.data.regexp('^media:cat:(\\d+):clear$')` | - |

### routers/categories/prices.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_prices_start` | callback_query | `-` | `F.data.regexp('^category:(\\d+):prices$')` | - |
| `cb_prices_update` | callback_query | `-` | `F.data.regexp('^category:(\\d+):prices:update$')` | - |
| `cb_price_text` | callback_query | `-` | `F.data.regexp('^price:cat:(\\d+):text$')` | PriceInputFSM.text_input |
| `fsm_price_text_input` | message | `PriceInputFSM.text_input` | `-` | - |
| `cb_price_excel` | callback_query | `-` | `F.data.regexp('^price:cat:(\\d+):excel$')` | PriceInputFSM.file_upload |
| `fsm_price_file_upload` | message | `PriceInputFSM.file_upload` | `-` | - |
| `fsm_price_save_text` | callback_query | `PriceInputFSM.text_input` | `F.data == 'price:save'` | CLEAR |
| `fsm_price_save_excel` | callback_query | `PriceInputFSM.file_upload` | `F.data == 'price:save'` | CLEAR |
| `cb_price_clear` | callback_query | `-` | `F.data.regexp('^price:cat:(\\d+):clear$')` | - |
| `fsm_price_choose_method_guard` | message | `PriceInputFSM.choose_method` | `-` | - |
| `fsm_price_file_upload_text_guard` | message | `PriceInputFSM.file_upload` | `-` | - |

### routers/categories/reviews.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_reviews_start` | callback_query | `-` | `F.data.regexp('^category:(\\d+):reviews$')` | ReviewGenerationFSM.quantity |
| `cb_reviews_regen_entry` | callback_query | `-` | `F.data.regexp('^category:(\\d+):reviews:regen$')` | ReviewGenerationFSM.quantity |
| `cb_review_quantity` | callback_query | `ReviewGenerationFSM.quantity` | `F.data.regexp('^review:qty:(\\d+):(\\d+)$')` | ReviewGenerationFSM.confirm_cost |
| `cb_review_confirm` | callback_query | `ReviewGenerationFSM.confirm_cost` | `F.data == 'review:confirm'` | ReviewGenerationFSM.generating, ReviewGenerationFSM.review, CLEAR |
| `cb_review_generating_guard` | callback_query | `ReviewGenerationFSM.generating` | `-` | - |
| `cb_review_save` | callback_query | `ReviewGenerationFSM.review` | `F.data == 'review:save'` | CLEAR |
| `cb_review_regen` | callback_query | `ReviewGenerationFSM.review` | `F.data == 'review:regen'` | ReviewGenerationFSM.generating, ReviewGenerationFSM.review, ReviewGenerationFSM.review, CLEAR |

### routers/help.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_help_main` | callback_query | `-` | `F.data == 'help:main'` | - |
| `cb_help_connect` | callback_query | `-` | `F.data == 'help:connect'` | - |
| `cb_help_project` | callback_query | `-` | `F.data == 'help:project'` | - |
| `cb_help_category` | callback_query | `-` | `F.data == 'help:category'` | - |
| `cb_help_publish` | callback_query | `-` | `F.data == 'help:publish'` | - |

### routers/payments.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `on_successful_payment` | message | `-` | `-` | - |

### routers/platforms/connections.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_connection_list` | callback_query | `-` | `F.data.regexp('^project:(\\d+):connections$')` | - |
| `cb_connection_card` | callback_query | `-` | `F.data.regexp('^conn:(\\d+):card$')` | - |
| `cb_connection_delete` | callback_query | `-` | `F.data.regexp('^conn:(\\d+):delete$')` | - |
| `cb_connection_delete_confirm` | callback_query | `-` | `F.data.regexp('^conn:(\\d+):delete:confirm$')` | - |
| `cb_wordpress_add` | callback_query | `-` | `F.data.regexp('^project:(\\d+):add:wordpress$')` | ConnectWordPressFSM.url |
| `fsm_wp_url` | message | `ConnectWordPressFSM.url` | `-` | ConnectWordPressFSM.login |
| `fsm_wp_login` | message | `ConnectWordPressFSM.login` | `-` | ConnectWordPressFSM.password |
| `fsm_wp_password` | message | `ConnectWordPressFSM.password` | `-` | CLEAR |
| `cb_telegram_add` | callback_query | `-` | `F.data.regexp('^project:(\\d+):add:telegram$')` | ConnectTelegramFSM.channel |
| `fsm_telegram_channel` | message | `ConnectTelegramFSM.channel` | `-` | ConnectTelegramFSM.token |
| `fsm_telegram_token` | message | `ConnectTelegramFSM.token` | `-` | CLEAR |
| `cb_vk_add` | callback_query | `-` | `F.data.regexp('^project:(\\d+):add:vk$')` | ConnectVKFSM.token |
| `fsm_vk_token` | message | `ConnectVKFSM.token` | `-` | ConnectVKFSM.select_group, CLEAR |
| `cb_vk_select_group` | callback_query | `ConnectVKFSM.select_group` | `F.data.startswith('vk_group:')` | CLEAR |
| `cb_pinterest_add` | callback_query | `-` | `F.data.regexp('^project:(\\d+):add:pinterest$')` | ConnectPinterestFSM.oauth_callback |
| `cb_pinterest_select_board` | callback_query | `ConnectPinterestFSM.select_board` | `F.data.startswith('pin_board:')` | CLEAR |

### routers/platforms/settings.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_override_stub` | callback_query | `-` | `F.data.regexp('^category:(\\d+):override:(\\w+)$')` | - |

### routers/profile.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_profile` | callback_query | `-` | `F.data == 'profile:main'` | - |
| `cb_history` | callback_query | `-` | `F.data == 'profile:history'` | - |
| `cb_referral` | callback_query | `-` | `F.data == 'profile:referral'` | - |

### routers/projects/card.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_project_card` | callback_query | `-` | `F.data.regexp('^project:(\\d+):card$')` | - |
| `cb_project_feature_stub` | callback_query | `-` | `F.data.regexp('^project:(\\d+):timezone$')` | - |
| `cb_project_delete` | callback_query | `-` | `F.data.regexp('^project:(\\d+):delete$')` | - |
| `cb_project_delete_confirm` | callback_query | `-` | `F.data.regexp('^project:(\\d+):delete:confirm$')` | - |

### routers/projects/create.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_project_new` | callback_query | `-` | `F.data == 'projects:new'` | ProjectCreateFSM.name |
| `fsm_project_name` | message | `ProjectCreateFSM.name` | `-` | ProjectCreateFSM.company_name |
| `fsm_project_company` | message | `ProjectCreateFSM.company_name` | `-` | ProjectCreateFSM.specialization |
| `fsm_project_spec` | message | `ProjectCreateFSM.specialization` | `-` | ProjectCreateFSM.website_url |
| `fsm_project_url` | message | `ProjectCreateFSM.website_url` | `-` | CLEAR |
| `cb_project_edit` | callback_query | `-` | `F.data.regexp('^project:(\\d+):edit$')` | - |
| `cb_project_field` | callback_query | `-` | `F.data.regexp('^project:(\\d+):field:(\\w+)$')` | ProjectEditFSM.field_value |
| `fsm_project_field_value` | message | `ProjectEditFSM.field_value` | `-` | CLEAR |

### routers/projects/list.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_project_list` | callback_query | `-` | `F.data == 'projects:list'` | - |
| `cb_project_page` | callback_query | `-` | `F.data.startswith('page:projects:')` | - |

### routers/publishing/preview.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_article_start` | callback_query | `-` | `F.data.regexp('^category:(\\d+):publish:wp$')` | - |
| `cb_article_start_with_conn` | callback_query | `-` | `F.data.regexp('^category:(\\d+):publish:wp:(\\d...` | - |
| `cb_article_confirm` | callback_query | `ArticlePublishFSM.confirm_cost` | `F.data == 'pub:article:confirm'` | ArticlePublishFSM.generating, ArticlePublishFSM.preview, CLEAR |
| `cb_article_publish` | callback_query | `ArticlePublishFSM.preview` | `F.data == 'pub:article:publish'` | ArticlePublishFSM.publishing, ArticlePublishFSM.preview, ArticlePublishFSM.preview, CLEAR |
| `cb_article_regen` | callback_query | `ArticlePublishFSM.preview` | `F.data == 'pub:article:regen'` | ArticlePublishFSM.regenerating, ArticlePublishFSM.preview, ArticlePublishFSM.preview, ArticlePublishFSM.preview, CLEAR |
| `cb_article_cancel` | callback_query | `ArticlePublishFSM.preview` | `F.data == 'pub:article:cancel'` | CLEAR |
| `cb_article_publishing_guard` | callback_query | `ArticlePublishFSM.publishing` | `-` | - |
| `cb_article_regen_guard` | callback_query | `ArticlePublishFSM.regenerating` | `-` | - |

### routers/publishing/quick.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_publish_dispatch` | callback_query | `-` | `F.data.regexp('^category:(\\d+):publish$')` | - |
| `cb_quick_project` | callback_query | `-` | `F.data.regexp('^quick:project:(\\d+)$')` | - |
| `cb_quick_publish_target` | callback_query | `-` | `F.data.regexp('^quick:cat:(\\d+):(wp|tg|vk|pi):...` | - |
| `cb_quick_proj_page` | callback_query | `-` | `F.data.regexp('^page:quick_proj:(\\d+)$')` | - |
| `cb_quick_combo_page` | callback_query | `-` | `F.data.regexp('^page:quick_combo:(\\d+):(\\d+)$')` | - |

### routers/publishing/scheduler.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_scheduler_categories` | callback_query | `-` | `F.data.regexp('^project:(\\d+):scheduler$')` | - |
| `cb_scheduler_platforms` | callback_query | `-` | `F.data.regexp('^sched:cat:(\\d+)$')` | - |
| `cb_schedule_start` | callback_query | `-` | `F.data.regexp('^sched:cat:(\\d+):plt:(\\d+)$')` | ScheduleSetupFSM.select_days |
| `cb_schedule_toggle_day` | callback_query | `ScheduleSetupFSM.select_days` | `F.data.regexp('^sched:day:(\\w+)$')` | - |
| `cb_schedule_days_done` | callback_query | `ScheduleSetupFSM.select_days` | `F.data == 'sched:days:done'` | ScheduleSetupFSM.select_count |
| `cb_schedule_count` | callback_query | `ScheduleSetupFSM.select_count` | `F.data.regexp('^sched:count:(\\d)$')` | ScheduleSetupFSM.select_times |
| `cb_schedule_toggle_time` | callback_query | `ScheduleSetupFSM.select_times` | `F.data.regexp('^sched:time:(\\d{2}:\\d{2})$')` | - |
| `cb_schedule_times_done` | callback_query | `ScheduleSetupFSM.select_times` | `F.data == 'sched:times:done'` | CLEAR |
| `cb_schedule_toggle` | callback_query | `-` | `F.data.regexp('^schedule:(\\d+):toggle$')` | - |
| `cb_schedule_delete` | callback_query | `-` | `F.data.regexp('^schedule:(\\d+):delete$')` | - |

### routers/publishing/social.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_social_start` | callback_query | `-` | `F.data.regexp('^category:(\\d+):publish:(tg|vk|...` | SocialPostPublishFSM.confirm_cost |
| `cb_social_confirm` | callback_query | `SocialPostPublishFSM.confirm_cost` | `F.data == 'pub:social:confirm'` | SocialPostPublishFSM.generating, SocialPostPublishFSM.review, CLEAR |
| `cb_social_publish` | callback_query | `SocialPostPublishFSM.review` | `F.data == 'pub:social:publish'` | SocialPostPublishFSM.publishing, CLEAR |
| `cb_social_regen` | callback_query | `SocialPostPublishFSM.review` | `F.data == 'pub:social:regen'` | SocialPostPublishFSM.regenerating, SocialPostPublishFSM.review |
| `cb_social_cancel` | callback_query | `SocialPostPublishFSM.review` | `F.data == 'pub:social:cancel'` | CLEAR |
| `cb_social_publishing_guard` | callback_query | `SocialPostPublishFSM.publishing` | `-` | - |
| `cb_social_regen_guard` | callback_query | `SocialPostPublishFSM.regenerating` | `-` | - |

### routers/settings.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_settings_main` | callback_query | `-` | `F.data == 'settings:main'` | - |
| `cb_settings_stub` | callback_query | `-` | `F.data.in_({'settings:support', 'settings:about'})` | - |
| `cb_notifications` | callback_query | `-` | `F.data == 'settings:notifications'` | - |
| `cb_toggle_notify` | callback_query | `-` | `F.data.startswith('settings:notify:')` | - |

### routers/start.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cmd_start_deep_link` | message | `-` | `-` | CLEAR |
| `cmd_start` | message | `-` | `-` | CLEAR |
| `cmd_cancel` | message | `-` | `-` | CLEAR |
| `btn_cancel` | message | `-` | `-` | CLEAR |
| `cmd_help` | message | `-` | `-` | - |
| `cb_main_menu` | callback_query | `-` | `F.data == 'menu:main'` | CLEAR |
| `cb_help` | callback_query | `-` | `F.data == 'help:main'` | - |
| `btn_menu` | message | `-` | `-` | - |
| `btn_quick_publish` | message | `-` | `-` | - |
| `btn_admin_redirect` | message | `-` | `-` | - |
| `cb_stub` | callback_query | `-` | `F.data == 'stats:all'` | - |
| `fsm_non_text_guard` | message | `-` | `-` | - |

### routers/tariffs.py

| Handler | Type | State Filter | callback_data Filter | Transitions |
|---------|------|-------------|---------------------|-------------|
| `cb_tariffs_main` | callback_query | `-` | `F.data == 'tariffs:main'` | - |
| `cb_tariffs_topup` | callback_query | `-` | `F.data == 'tariffs:topup'` | - |
| `cb_package_select` | callback_query | `-` | `F.data.regexp('^tariff:(\\w+):select$')` | - |
| `cb_pay_stars` | callback_query | `-` | `F.data.regexp('^tariff:(\\w+):stars$')` | - |
| `cb_pay_yookassa` | callback_query | `-` | `F.data.regexp('^tariff:(\\w+):yk$')` | - |
| `cb_subscription_select` | callback_query | `-` | `F.data.regexp('^sub:(\\w+):select$')` | - |
| `cb_subscribe_stars` | callback_query | `-` | `F.data.regexp('^sub:(\\w+):stars$')` | - |
| `cb_subscribe_yookassa` | callback_query | `-` | `F.data.regexp('^sub:(\\w+):yk$')` | - |
| `cb_subscription_manage` | callback_query | `-` | `F.data == 'sub:manage'` | - |
| `cb_subscription_cancel` | callback_query | `-` | `F.data == 'sub:cancel'` | - |
| `cb_subscription_cancel_confirm` | callback_query | `-` | `F.data == 'sub:cancel:confirm'` | - |

## 3. Keyboards

Total: **70** keyboard builders

### cb_kw_results_cancel()
File: `routers/categories/keywords.py:439`

| Button Text | callback_data |
|-------------|---------------|
| К ключевым фразам | `back_cb` |

### cb_kw_upload_results_cancel()
File: `routers/categories/keywords.py:645`

| Button Text | callback_data |
|-------------|---------------|
| К ключевым фразам | `back_cb` |

### _connection_list_kb()
File: `routers/platforms/connections.py:104`

| Button Text | callback_data |
|-------------|---------------|
| Добавить WordPress-сайт | `project:{project_id}:add:wordpress` |
| Добавить Telegram | `project:{project_id}:add:telegram` |
| Добавить VK | `project:{project_id}:add:vk` |
| Добавить Pinterest | `project:{project_id}:add:pinterest` |
| К проекту | `project:{project_id}:card` |
| text | `conn:{id}:card` |

### _connection_card_kb()
File: `routers/platforms/connections.py:125`

| Button Text | callback_data |
|-------------|---------------|
| Удалить | `conn:{id}:delete` |
| К подключениям | `project:{project_id}:connections` |

### _connection_delete_confirm_kb()
File: `routers/platforms/connections.py:134`

| Button Text | callback_data |
|-------------|---------------|
| Да, удалить | `conn:{conn_id}:delete:confirm` |
| Отмена | `project:{project_id}:connections` |

### fsm_vk_token()
File: `routers/platforms/connections.py:596`

| Button Text | callback_data |
|-------------|---------------|
| text | `vk_group:{...}` |

### cb_article_cancel()
File: `routers/publishing/preview.py:680`

| Button Text | callback_data |
|-------------|---------------|
| К категории | `back_cb` |

### cb_social_cancel()
File: `routers/publishing/social.py:393`

| Button Text | callback_data |
|-------------|---------------|
| К категории | `category:{category_id}:card` |

### _handle_pinterest_auth()
File: `routers/start.py:153`

| Button Text | callback_data |
|-------------|---------------|
| text | `pin_board:{...}` |

### cb_pay_yookassa()
File: `routers/tariffs.py:111`

| Button Text | callback_data |
|-------------|---------------|
| Назад | `tariff:{name}:select` |

### cb_subscribe_stars()
File: `routers/tariffs.py:161`

| Button Text | callback_data |
|-------------|---------------|
| Назад | `sub:{name}:select` |

### cb_subscribe_yookassa()
File: `routers/tariffs.py:194`

| Button Text | callback_data |
|-------------|---------------|
| Назад | `sub:{name}:select` |

### description_confirm_kb()
File: `keyboards/category.py:10`

| Button Text | callback_data |
|-------------|---------------|
| Да, сгенерировать ({cost} ток.) | `desc:confirm` |
| Отмена | `category:{cat_id}:card` |

### description_result_kb()
File: `keyboards/category.py:19`

| Button Text | callback_data |
|-------------|---------------|
| Сохранить | `desc:save` |
| label | `desc:regen` |
| Отмена | `category:{cat_id}:card` |

### description_existing_kb()
File: `keyboards/category.py:30`

| Button Text | callback_data |
|-------------|---------------|
| Перегенерировать | `category:{cat_id}:description:regen` |
| К категории | `category:{cat_id}:card` |

### review_quantity_kb()
File: `keyboards/category.py:44`

| Button Text | callback_data |
|-------------|---------------|
| Отмена | `category:{cat_id}:card` |
| str(n) | `review:qty:{cat_id}:{n}` |

### review_confirm_kb()
File: `keyboards/category.py:54`

| Button Text | callback_data |
|-------------|---------------|
| Да, сгенерировать ({cost} ток.) | `review:confirm` |
| Отмена | `category:{cat_id}:card` |

### review_result_kb()
File: `keyboards/category.py:63`

| Button Text | callback_data |
|-------------|---------------|
| Сохранить | `review:save` |
| label | `review:regen` |
| Отмена | `category:{cat_id}:card` |

### review_existing_kb()
File: `keyboards/category.py:74`

| Button Text | callback_data |
|-------------|---------------|
| Перегенерировать ({count} шт.) | `category:{cat_id}:reviews:regen` |
| К категории | `category:{cat_id}:card` |

### price_method_kb()
File: `keyboards/category.py:88`

| Button Text | callback_data |
|-------------|---------------|
| Ввести текстом | `price:cat:{cat_id}:text` |
| Загрузить Excel | `price:cat:{cat_id}:excel` |
| К категории | `category:{cat_id}:card` |

### price_result_kb()
File: `keyboards/category.py:98`

| Button Text | callback_data |
|-------------|---------------|
| Сохранить | `price:save` |
| К категории | `category:{cat_id}:card` |

### price_existing_kb()
File: `keyboards/category.py:107`

| Button Text | callback_data |
|-------------|---------------|
| Обновить | `category:{cat_id}:prices:update` |
| Очистить | `price:cat:{cat_id}:clear` |
| К категории | `category:{cat_id}:card` |

### media_menu_kb()
File: `keyboards/category.py:122`

| Button Text | callback_data |
|-------------|---------------|
| Загрузить файлы | `media:cat:{cat_id}:upload` |
| К категории | `category:{cat_id}:card` |
| Очистить | `media:cat:{cat_id}:clear` |

### admin_dashboard_kb()
File: `keyboards/category.py:138`

| Button Text | callback_data |
|-------------|---------------|
| Мониторинг | `admin:monitoring` |
| Сообщения всем | `admin:broadcast` |
| Затраты API | `admin:costs` |
| Назад | `menu:main` |

### admin_broadcast_audience_kb()
File: `keyboards/category.py:149`

| Button Text | callback_data |
|-------------|---------------|
| Всем | `admin:bc:all` |
| Активные 7д | `admin:bc:active_7d` |
| Активные 30д | `admin:bc:active_30d` |
| Платные | `admin:bc:paid` |
| Отмена | `admin:main` |

### admin_broadcast_confirm_kb()
File: `keyboards/category.py:161`

| Button Text | callback_data |
|-------------|---------------|
| Да, отправить ({count} чел.) | `admin:bc:confirm` |
| Отмена | `admin:main` |

### help_main_kb()
File: `keyboards/category.py:175`

| Button Text | callback_data |
|-------------|---------------|
| Первое подключение | `help:connect` |
| Создание проекта | `help:project` |
| Категории | `help:category` |
| Публикация | `help:publish` |
| Главное меню | `menu:main` |

### help_back_kb()
File: `keyboards/category.py:187`

| Button Text | callback_data |
|-------------|---------------|
| Назад к помощи | `help:main` |
| Главное меню | `menu:main` |

### dashboard_kb()
File: `keyboards/inline.py:14`

| Button Text | callback_data |
|-------------|---------------|
| Проекты | `projects:list` |
| Профиль | `profile:main` |
| Тарифы | `tariffs:main` |
| Настройки | `settings:main` |
| Помощь | `help:main` |

### project_list_kb()
File: `keyboards/inline.py:58`

| Button Text | callback_data |
|-------------|---------------|
| Создать проект | `projects:new` |
| Статистика | `stats:all` |
| Главное меню | `menu:main` |
| Создать проект | `projects:new` |
| Помощь | `help:main` |

### project_card_kb()
File: `keyboards/inline.py:91`

| Button Text | callback_data |
|-------------|---------------|
| Редактировать данные | `project:{id}:edit` |
| Управление категориями | `project:{id}:categories` |
| Создать категорию | `project:{id}:cat:new` |
| Подключения платформ | `project:{id}:connections` |
| Планировщик публикаций | `project:{id}:scheduler` |
| Анализ сайта | `project:{id}:audit` |
| Часовой пояс: {tz} | `project:{id}:timezone` |
| Удалить проект | `project:{id}:delete` |
| К списку проектов | `projects:list` |

### project_edit_fields_kb()
File: `keyboards/inline.py:110`

| Button Text | callback_data |
|-------------|---------------|
| Назад | `project:{id}:card` |
| display | `project:{id}:field:{field_name}` |

### project_delete_confirm_kb()
File: `keyboards/inline.py:127`

| Button Text | callback_data |
|-------------|---------------|
| Да, удалить | `project:{project_id}:delete:confirm` |
| Отмена | `project:{project_id}:card` |

### category_list_kb()
File: `keyboards/inline.py:141`

| Button Text | callback_data |
|-------------|---------------|
| Добавить категорию | `project:{project_id}:cat:new` |
| К проекту | `project:{project_id}:card` |

### category_card_kb()
File: `keyboards/inline.py:162`

| Button Text | callback_data |
|-------------|---------------|
| Опубликовать | `category:{id}:publish` |
| Ключевые фразы | `category:{id}:keywords` |
| Описание | `category:{id}:description` |
| Цены | `category:{id}:prices` |
| Отзывы | `category:{id}:reviews` |
| Медиа | `category:{id}:media` |
| Настройки изображений | `category:{id}:img_settings` |
| Настройки текста | `category:{id}:text_settings` |
| Удалить категорию | `category:{id}:delete` |
| К списку категорий | `project:{project_id}:categories` |

### category_delete_confirm_kb()
File: `keyboards/inline.py:185`

| Button Text | callback_data |
|-------------|---------------|
| Да, удалить | `category:{id}:delete:confirm` |
| Отмена | `category:{id}:card` |

### settings_main_kb()
File: `keyboards/inline.py:199`

| Button Text | callback_data |
|-------------|---------------|
| Уведомления | `settings:notifications` |
| Техподдержка | `settings:support` |
| О боте | `settings:about` |
| Главное меню | `menu:main` |

### profile_main_kb()
File: `keyboards/inline.py:215`

| Button Text | callback_data |
|-------------|---------------|
| История расходов | `profile:history` |
| Пополнить | `tariffs:main` |
| Реферальная программа | `profile:referral` |
| Главное меню | `menu:main` |

### profile_history_kb()
File: `keyboards/inline.py:226`

| Button Text | callback_data |
|-------------|---------------|
| К профилю | `profile:main` |

### profile_referral_kb()
File: `keyboards/inline.py:234`

| Button Text | callback_data |
|-------------|---------------|
| К профилю | `profile:main` |

### settings_notifications_kb()
File: `keyboards/inline.py:245`

| Button Text | callback_data |
|-------------|---------------|
| Публикации: {pub_status} | `settings:notify:publications` |
| Баланс: {bal_status} | `settings:notify:balance` |
| Новости: {news_status} | `settings:notify:news` |
| Назад | `settings:main` |

### tariffs_main_kb()
File: `keyboards/inline.py:266`

| Button Text | callback_data |
|-------------|---------------|
| Пополнить баланс | `tariffs:topup` |
| Главное меню | `menu:main` |
| label | `sub:{name}:select` |
| Моя подписка | `sub:manage` |

### package_list_kb()
File: `keyboards/inline.py:280`

| Button Text | callback_data |
|-------------|---------------|
| Назад | `tariffs:main` |
| label | `tariff:{name}:select` |

### package_pay_kb()
File: `keyboards/inline.py:292`

| Button Text | callback_data |
|-------------|---------------|
| Оплатить Stars ⭐ ({stars} Stars) | `tariff:{package_name}:stars` |
| yk_label | `tariff:{package_name}:yk` |
| Назад | `tariffs:topup` |

### subscription_pay_kb()
File: `keyboards/inline.py:312`

| Button Text | callback_data |
|-------------|---------------|
| Оплатить Stars ⭐ ({stars} Stars) | `sub:{sub_name}:stars` |
| Оплатить картой (ЮKassa) | `sub:{sub_name}:yk` |
| Назад | `tariffs:main` |

### subscription_manage_kb()
File: `keyboards/inline.py:327`

| Button Text | callback_data |
|-------------|---------------|
| Изменить тариф | `tariffs:main` |
| Отменить подписку | `sub:cancel` |
| К тарифам | `tariffs:main` |

### subscription_cancel_confirm_kb()
File: `keyboards/inline.py:337`

| Button Text | callback_data |
|-------------|---------------|
| Да, отменить | `sub:cancel:confirm` |
| Оставить | `sub:manage` |

### paginate()
File: `keyboards/pagination.py:11`

| Button Text | callback_data |
|-------------|---------------|
| item_text_fn(item) | `item_callback_fn(item)` |
| ◀ Назад | `page_callback_fn(page - 1)` |
| Ещё ▼ | `page_callback_fn(page + 1)` |

### article_confirm_kb()
File: `keyboards/publish.py:13`

| Button Text | callback_data |
|-------------|---------------|
| Да, сгенерировать ({cost} токенов) | `pub:article:confirm` |
| Отмена | `category:{category_id}:card` |

### article_preview_kb()
File: `keyboards/publish.py:22`

| Button Text | callback_data |
|-------------|---------------|
| Опубликовать | `pub:article:publish` |
| Перегенерировать ({remaining}/2) | `pub:article:regen` |
| Отмена | `pub:article:cancel` |

### social_confirm_kb()
File: `keyboards/publish.py:41`

| Button Text | callback_data |
|-------------|---------------|
| Да, сгенерировать ({cost} токенов) | `pub:social:confirm` |
| Отмена | `category:{category_id}:card` |

### social_review_kb()
File: `keyboards/publish.py:52`

| Button Text | callback_data |
|-------------|---------------|
| Опубликовать | `pub:social:publish` |
| Перегенерировать ({remaining}/2) | `pub:social:regen` |
| Отмена | `pub:social:cancel` |

### insufficient_balance_kb()
File: `keyboards/publish.py:71`

| Button Text | callback_data |
|-------------|---------------|
| Пополнить | `tariffs:topup` |
| Отмена | `menu:main` |

### quick_combo_list_kb()
File: `keyboards/publish.py:97`

| Button Text | callback_data |
|-------------|---------------|
| Назад | `menu:main` |

### quick_wp_choice_kb()
File: `keyboards/publish.py:130`

| Button Text | callback_data |
|-------------|---------------|
| Назад | `menu:main` |
| conn.identifier | `quick:cat:{category_id}:wp:{id}` |

### publish_platform_choice_kb()
File: `keyboards/publish.py:150`

| Button Text | callback_data |
|-------------|---------------|
| Назад | `category:{category_id}:card` |
| label | `category:{category_id}:publish:{ps}:{id}` |

### keywords_main_kb()
File: `keyboards/publish.py:179`

| Button Text | callback_data |
|-------------|---------------|
| Подобрать фразы | `category:{category_id}:kw:generate` |
| Загрузить свои | `category:{category_id}:kw:upload` |
| К категории | `category:{category_id}:card` |

### keyword_quantity_kb()
File: `keyboards/publish.py:189`

| Button Text | callback_data |
|-------------|---------------|
| str(n) | `kw:qty:{category_id}:{n}` |

### keyword_confirm_kb()
File: `keyboards/publish.py:198`

| Button Text | callback_data |
|-------------|---------------|
| Да, генерировать ({cost} токенов) | `kw:confirm` |
| Отмена | `category:{category_id}:card` |

### keyword_results_kb()
File: `keyboards/publish.py:207`

| Button Text | callback_data |
|-------------|---------------|
| Сохранить | `kw:save` |
| Отменить | `kw:results:cancel` |
| К категории | `category:{category_id}:card` |

### audit_menu_kb()
File: `keyboards/publish.py:222`

| Button Text | callback_data |
|-------------|---------------|
| label | `project:{project_id}:audit:run` |
| Анализ конкурентов | `project:{project_id}:competitor` |
| К проекту | `project:{project_id}:card` |

### audit_results_kb()
File: `keyboards/publish.py:233`

| Button Text | callback_data |
|-------------|---------------|
| Перезапустить | `project:{project_id}:audit:run` |
| Анализ конкурентов | `project:{project_id}:competitor` |
| К проекту | `project:{project_id}:card` |

### competitor_confirm_kb()
File: `keyboards/publish.py:248`

| Button Text | callback_data |
|-------------|---------------|
| Да, анализировать ({cost} токенов) | `comp:confirm` |
| Отмена | `project:{project_id}:card` |

### competitor_results_kb()
File: `keyboards/publish.py:257`

| Button Text | callback_data |
|-------------|---------------|
| К проекту | `project:{project_id}:card` |

### scheduler_category_list_kb()
File: `keyboards/schedule.py:34`

| Button Text | callback_data |
|-------------|---------------|
| К проекту | `project:{project_id}:card` |
| name | `sched:cat:{id}` |

### scheduler_platform_list_kb()
File: `keyboards/schedule.py:48`

| Button Text | callback_data |
|-------------|---------------|
| К планировщику | `project:{project_id}:scheduler` |
| text | `sched:cat:{category_id}:plt:{id}` |

### schedule_days_kb()
File: `keyboards/schedule.py:80`

| Button Text | callback_data |
|-------------|---------------|
| Готово | `sched:days:done` |
| {day_name}{marker} | `sched:day:{day_code}` |

### schedule_count_kb()
File: `keyboards/schedule.py:91`

| Button Text | callback_data |
|-------------|---------------|
| str(n) | `sched:count:{n}` |

### schedule_times_kb()
File: `keyboards/schedule.py:100`

| Button Text | callback_data |
|-------------|---------------|
| Готово ({*}/{max_count}) | `sched:times:done` |
| {slot}{marker} | `sched:time:{slot}` |

### schedule_summary_kb()
File: `keyboards/schedule.py:114`

| Button Text | callback_data |
|-------------|---------------|
| Отключить | `schedule:{schedule_id}:toggle` |
| Удалить | `schedule:{schedule_id}:delete` |
| К планировщику | `project:{project_id}:scheduler` |

## 4. Navigation Graph (callback_data links)

Which keyboard button leads to which handler:

**cb_kw_results_cancel()** (routers/categories/keywords.py):
  - [К ключевым фразам] `back_cb` -> ???

**cb_kw_upload_results_cancel()** (routers/categories/keywords.py):
  - [К ключевым фразам] `back_cb` -> ???

**_connection_list_kb()** (routers/platforms/connections.py):
  - [Добавить WordPress-сайт] `project:{project_id}:add:wordpress` -> `cb_wordpress_add` (routers/platforms/connections.py:292)
  - [Добавить Telegram] `project:{project_id}:add:telegram` -> `cb_telegram_add` (routers/platforms/connections.py:432)
  - [Добавить VK] `project:{project_id}:add:vk` -> `cb_vk_add` (routers/platforms/connections.py:571)
  - [Добавить Pinterest] `project:{project_id}:add:pinterest` -> `cb_pinterest_add` (routers/platforms/connections.py:738)
  - [К проекту] `project:{project_id}:card` -> `cb_project_card` (routers/projects/card.py:89)
  - [text] `conn:{id}:card` -> `cb_connection_card` (routers/platforms/connections.py:187)

**_connection_card_kb()** (routers/platforms/connections.py):
  - [Удалить] `conn:{id}:delete` -> `cb_connection_delete` (routers/platforms/connections.py:218)
  - [К подключениям] `project:{project_id}:connections` -> `cb_connection_list` (routers/platforms/connections.py:157)

**_connection_delete_confirm_kb()** (routers/platforms/connections.py):
  - [Да, удалить] `conn:{conn_id}:delete:confirm` -> `cb_connection_delete_confirm` (routers/platforms/connections.py:245)
  - [Отмена] `project:{project_id}:connections` -> `cb_connection_list` (routers/platforms/connections.py:157)

**fsm_vk_token()** (routers/platforms/connections.py):
  - [text] `vk_group:{...}` -> `cb_vk_select_group` (routers/platforms/connections.py:678)

**cb_article_cancel()** (routers/publishing/preview.py):
  - [К категории] `back_cb` -> ???

**cb_social_cancel()** (routers/publishing/social.py):
  - [К категории] `category:{category_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**_handle_pinterest_auth()** (routers/start.py):
  - [text] `pin_board:{...}` -> `cb_pinterest_select_board` (routers/platforms/connections.py:791)

**cb_pay_yookassa()** (routers/tariffs.py):
  - [Назад] `tariff:{name}:select` -> `cb_package_select` (routers/tariffs.py:67)

**cb_subscribe_stars()** (routers/tariffs.py):
  - [Назад] `sub:{name}:select` -> `cb_subscription_select` (routers/tariffs.py:143)

**cb_subscribe_yookassa()** (routers/tariffs.py):
  - [Назад] `sub:{name}:select` -> `cb_subscription_select` (routers/tariffs.py:143)

**description_confirm_kb()** (keyboards/category.py):
  - [Да, сгенерировать ({cost} ток.)] `desc:confirm` -> `cb_description_confirm` (routers/categories/description.py:140)
  - [Отмена] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**description_result_kb()** (keyboards/category.py):
  - [Сохранить] `desc:save` -> `cb_description_save` (routers/categories/description.py:201)
  - [label] `desc:regen` -> `cb_description_regen` (routers/categories/description.py:237)
  - [Отмена] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**description_existing_kb()** (keyboards/category.py):
  - [Перегенерировать] `category:{cat_id}:description:regen` -> `cb_description_regen_entry` (routers/categories/description.py:109)
  - [К категории] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**review_quantity_kb()** (keyboards/category.py):
  - [Отмена] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)
  - [str(n)] `review:qty:{cat_id}:{n}` -> `cb_review_quantity` (routers/categories/reviews.py:180)

**review_confirm_kb()** (keyboards/category.py):
  - [Да, сгенерировать ({cost} ток.)] `review:confirm` -> `cb_review_confirm` (routers/categories/reviews.py:214)
  - [Отмена] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**review_result_kb()** (keyboards/category.py):
  - [Сохранить] `review:save` -> `cb_review_save` (routers/categories/reviews.py:278)
  - [label] `review:regen` -> `cb_review_regen` (routers/categories/reviews.py:314)
  - [Отмена] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**review_existing_kb()** (keyboards/category.py):
  - [Перегенерировать ({count} шт.)] `category:{cat_id}:reviews:regen` -> `cb_reviews_regen_entry` (routers/categories/reviews.py:148)
  - [К категории] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**price_method_kb()** (keyboards/category.py):
  - [Ввести текстом] `price:cat:{cat_id}:text` -> `cb_price_text` (routers/categories/prices.py:125)
  - [Загрузить Excel] `price:cat:{cat_id}:excel` -> `cb_price_excel` (routers/categories/prices.py:190)
  - [К категории] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**price_result_kb()** (keyboards/category.py):
  - [Сохранить] `price:save` -> `fsm_price_save_text` (routers/categories/prices.py:288)
  - [К категории] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**price_existing_kb()** (keyboards/category.py):
  - [Обновить] `category:{cat_id}:prices:update` -> `cb_prices_update` (routers/categories/prices.py:104)
  - [Очистить] `price:cat:{cat_id}:clear` -> `cb_price_clear` (routers/categories/prices.py:355)
  - [К категории] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**media_menu_kb()** (keyboards/category.py):
  - [Загрузить файлы] `media:cat:{cat_id}:upload` -> `cb_media_upload_prompt` (routers/categories/media.py:78)
  - [К категории] `category:{cat_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)
  - [Очистить] `media:cat:{cat_id}:clear` -> `cb_media_clear` (routers/categories/media.py:178)

**admin_dashboard_kb()** (keyboards/category.py):
  - [Мониторинг] `admin:monitoring` -> `cb_admin_monitoring` (routers/admin/dashboard.py:99)
  - [Сообщения всем] `admin:broadcast` -> `cb_broadcast_start` (routers/admin/broadcast.py:49)
  - [Затраты API] `admin:costs` -> `cb_admin_costs` (routers/admin/dashboard.py:136)
  - [Назад] `menu:main` -> `cb_main_menu` (routers/start.py:305)

**admin_broadcast_audience_kb()** (keyboards/category.py):
  - [Всем] `admin:bc:all` -> `cb_broadcast_audience` (routers/admin/broadcast.py:77)
  - [Активные 7д] `admin:bc:active_7d` -> `cb_broadcast_audience` (routers/admin/broadcast.py:77)
  - [Активные 30д] `admin:bc:active_30d` -> `cb_broadcast_audience` (routers/admin/broadcast.py:77)
  - [Платные] `admin:bc:paid` -> `cb_broadcast_audience` (routers/admin/broadcast.py:77)
  - [Отмена] `admin:main` -> `cb_admin_main` (routers/admin/dashboard.py:79)

**admin_broadcast_confirm_kb()** (keyboards/category.py):
  - [Да, отправить ({count} чел.)] `admin:bc:confirm` -> `cb_broadcast_confirm` (routers/admin/broadcast.py:150)
  - [Отмена] `admin:main` -> `cb_admin_main` (routers/admin/dashboard.py:79)

**help_main_kb()** (keyboards/category.py):
  - [Первое подключение] `help:connect` -> `cb_help_connect` (routers/help.py:116)
  - [Создание проекта] `help:project` -> `cb_help_project` (routers/help.py:126)
  - [Категории] `help:category` -> `cb_help_category` (routers/help.py:136)
  - [Публикация] `help:publish` -> `cb_help_publish` (routers/help.py:146)
  - [Главное меню] `menu:main` -> `cb_main_menu` (routers/start.py:305)

**help_back_kb()** (keyboards/category.py):
  - [Назад к помощи] `help:main` -> `cb_help_main` (routers/help.py:106)
  - [Главное меню] `menu:main` -> `cb_main_menu` (routers/start.py:305)

**dashboard_kb()** (keyboards/inline.py):
  - [Проекты] `projects:list` -> `cb_project_list` (routers/projects/list.py:16)
  - [Профиль] `profile:main` -> `cb_profile` (routers/profile.py:123)
  - [Тарифы] `tariffs:main` -> `cb_tariffs_main` (routers/tariffs.py:36)
  - [Настройки] `settings:main` -> `cb_settings_main` (routers/settings.py:20)
  - [Помощь] `help:main` -> `cb_help_main` (routers/help.py:106)

**project_list_kb()** (keyboards/inline.py):
  - [Создать проект] `projects:new` -> `cb_project_new` (routers/projects/create.py:116)
  - [Статистика] `stats:all` -> `cb_stub` (routers/start.py:361)
  - [Главное меню] `menu:main` -> `cb_main_menu` (routers/start.py:305)
  - [Создать проект] `projects:new` -> `cb_project_new` (routers/projects/create.py:116)
  - [Помощь] `help:main` -> `cb_help_main` (routers/help.py:106)

**project_card_kb()** (keyboards/inline.py):
  - [Редактировать данные] `project:{id}:edit` -> `cb_project_edit` (routers/projects/create.py:222)
  - [Управление категориями] `project:{id}:categories` -> `cb_category_list` (routers/categories/manage.py:107)
  - [Создать категорию] `project:{id}:cat:new` -> `cb_category_new` (routers/categories/manage.py:188)
  - [Подключения платформ] `project:{id}:connections` -> `cb_connection_list` (routers/platforms/connections.py:157)
  - [Планировщик публикаций] `project:{id}:scheduler` -> `cb_scheduler_categories` (routers/publishing/scheduler.py:56)
  - [Анализ сайта] `project:{id}:audit` -> `cb_project_audit` (routers/analysis.py:143)
  - [Часовой пояс: {tz}] `project:{id}:timezone` -> `cb_project_feature_stub` (routers/projects/card.py:126)
  - [Удалить проект] `project:{id}:delete` -> `cb_project_delete` (routers/projects/card.py:137)
  - [К списку проектов] `projects:list` -> `cb_project_list` (routers/projects/list.py:16)

**project_edit_fields_kb()** (keyboards/inline.py):
  - [Назад] `project:{id}:card` -> `cb_project_card` (routers/projects/card.py:89)
  - [display] `project:{id}:field:{field_name}` -> `cb_project_field` (routers/projects/create.py:239)

**project_delete_confirm_kb()** (keyboards/inline.py):
  - [Да, удалить] `project:{project_id}:delete:confirm` -> `cb_project_delete_confirm` (routers/projects/card.py:154)
  - [Отмена] `project:{project_id}:card` -> `cb_project_card` (routers/projects/card.py:89)

**category_list_kb()** (keyboards/inline.py):
  - [Добавить категорию] `project:{project_id}:cat:new` -> `cb_category_new` (routers/categories/manage.py:188)
  - [К проекту] `project:{project_id}:card` -> `cb_project_card` (routers/projects/card.py:89)

**category_card_kb()** (keyboards/inline.py):
  - [Опубликовать] `category:{id}:publish` -> `cb_publish_dispatch` (routers/publishing/quick.py:82)
  - [Ключевые фразы] `category:{id}:keywords` -> `cb_keywords_main` (routers/categories/keywords.py:125)
  - [Описание] `category:{id}:description` -> `cb_description_start` (routers/categories/description.py:65)
  - [Цены] `category:{id}:prices` -> `cb_prices_start` (routers/categories/prices.py:67)
  - [Отзывы] `category:{id}:reviews` -> `cb_reviews_start` (routers/categories/reviews.py:111)
  - [Медиа] `category:{id}:media` -> `cb_media_start` (routers/categories/media.py:51)
  - [Настройки изображений] `category:{id}:img_settings` -> `cb_category_feature_stub` (routers/categories/manage.py:174)
  - [Настройки текста] `category:{id}:text_settings` -> `cb_category_feature_stub` (routers/categories/manage.py:174)
  - [Удалить категорию] `category:{id}:delete` -> `cb_category_delete` (routers/categories/manage.py:246)
  - [К списку категорий] `project:{project_id}:categories` -> `cb_category_list` (routers/categories/manage.py:107)

**category_delete_confirm_kb()** (keyboards/inline.py):
  - [Да, удалить] `category:{id}:delete:confirm` -> `cb_category_delete_confirm` (routers/categories/manage.py:264)
  - [Отмена] `category:{id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**settings_main_kb()** (keyboards/inline.py):
  - [Уведомления] `settings:notifications` -> `cb_notifications` (routers/settings.py:36)
  - [Техподдержка] `settings:support` -> ???
  - [О боте] `settings:about` -> ???
  - [Главное меню] `menu:main` -> `cb_main_menu` (routers/start.py:305)

**profile_main_kb()** (keyboards/inline.py):
  - [История расходов] `profile:history` -> `cb_history` (routers/profile.py:138)
  - [Пополнить] `tariffs:main` -> `cb_tariffs_main` (routers/tariffs.py:36)
  - [Реферальная программа] `profile:referral` -> `cb_referral` (routers/profile.py:163)
  - [Главное меню] `menu:main` -> `cb_main_menu` (routers/start.py:305)

**profile_history_kb()** (keyboards/inline.py):
  - [К профилю] `profile:main` -> `cb_profile` (routers/profile.py:123)

**profile_referral_kb()** (keyboards/inline.py):
  - [К профилю] `profile:main` -> `cb_profile` (routers/profile.py:123)

**settings_notifications_kb()** (keyboards/inline.py):
  - [Публикации: {pub_status}] `settings:notify:publications` -> `cb_toggle_notify` (routers/settings.py:57)
  - [Баланс: {bal_status}] `settings:notify:balance` -> `cb_toggle_notify` (routers/settings.py:57)
  - [Новости: {news_status}] `settings:notify:news` -> `cb_toggle_notify` (routers/settings.py:57)
  - [Назад] `settings:main` -> `cb_settings_main` (routers/settings.py:20)

**tariffs_main_kb()** (keyboards/inline.py):
  - [Пополнить баланс] `tariffs:topup` -> `cb_tariffs_topup` (routers/tariffs.py:57)
  - [Главное меню] `menu:main` -> `cb_main_menu` (routers/start.py:305)
  - [label] `sub:{name}:select` -> `cb_subscription_select` (routers/tariffs.py:143)
  - [Моя подписка] `sub:manage` -> `cb_subscription_manage` (routers/tariffs.py:229)

**package_list_kb()** (keyboards/inline.py):
  - [Назад] `tariffs:main` -> `cb_tariffs_main` (routers/tariffs.py:36)
  - [label] `tariff:{name}:select` -> `cb_package_select` (routers/tariffs.py:67)

**package_pay_kb()** (keyboards/inline.py):
  - [Оплатить Stars ⭐ ({stars} Stars)] `tariff:{package_name}:stars` -> `cb_pay_stars` (routers/tariffs.py:86)
  - [yk_label] `tariff:{package_name}:yk` -> `cb_pay_yookassa` (routers/tariffs.py:111)
  - [Назад] `tariffs:topup` -> `cb_tariffs_topup` (routers/tariffs.py:57)

**subscription_pay_kb()** (keyboards/inline.py):
  - [Оплатить Stars ⭐ ({stars} Stars)] `sub:{sub_name}:stars` -> `cb_subscribe_stars` (routers/tariffs.py:161)
  - [Оплатить картой (ЮKassa)] `sub:{sub_name}:yk` -> `cb_subscribe_yookassa` (routers/tariffs.py:194)
  - [Назад] `tariffs:main` -> `cb_tariffs_main` (routers/tariffs.py:36)

**subscription_manage_kb()** (keyboards/inline.py):
  - [Изменить тариф] `tariffs:main` -> `cb_tariffs_main` (routers/tariffs.py:36)
  - [Отменить подписку] `sub:cancel` -> `cb_subscription_cancel` (routers/tariffs.py:249)
  - [К тарифам] `tariffs:main` -> `cb_tariffs_main` (routers/tariffs.py:36)

**subscription_cancel_confirm_kb()** (keyboards/inline.py):
  - [Да, отменить] `sub:cancel:confirm` -> `cb_subscription_cancel_confirm` (routers/tariffs.py:268)
  - [Оставить] `sub:manage` -> `cb_subscription_manage` (routers/tariffs.py:229)

**paginate()** (keyboards/pagination.py):
  - [item_text_fn(item)] `item_callback_fn(item)` -> ???
  - [◀ Назад] `page_callback_fn(page - 1)` -> ???
  - [Ещё ▼] `page_callback_fn(page + 1)` -> ???

**article_confirm_kb()** (keyboards/publish.py):
  - [Да, сгенерировать ({cost} токенов)] `pub:article:confirm` -> `cb_article_confirm` (routers/publishing/preview.py:287)
  - [Отмена] `category:{category_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**article_preview_kb()** (keyboards/publish.py):
  - [Опубликовать] `pub:article:publish` -> `cb_article_publish` (routers/publishing/preview.py:467)
  - [Перегенерировать ({remaining}/2)] `pub:article:regen` -> `cb_article_regen` (routers/publishing/preview.py:566)
  - [Отмена] `pub:article:cancel` -> `cb_article_cancel` (routers/publishing/preview.py:680)

**social_confirm_kb()** (keyboards/publish.py):
  - [Да, сгенерировать ({cost} токенов)] `pub:social:confirm` -> `cb_social_confirm` (routers/publishing/social.py:173)
  - [Отмена] `category:{category_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**social_review_kb()** (keyboards/publish.py):
  - [Опубликовать] `pub:social:publish` -> `cb_social_publish` (routers/publishing/social.py:261)
  - [Перегенерировать ({remaining}/2)] `pub:social:regen` -> `cb_social_regen` (routers/publishing/social.py:325)
  - [Отмена] `pub:social:cancel` -> `cb_social_cancel` (routers/publishing/social.py:393)

**insufficient_balance_kb()** (keyboards/publish.py):
  - [Пополнить] `tariffs:topup` -> `cb_tariffs_topup` (routers/tariffs.py:57)
  - [Отмена] `menu:main` -> `cb_main_menu` (routers/start.py:305)

**quick_combo_list_kb()** (keyboards/publish.py):
  - [Назад] `menu:main` -> `cb_main_menu` (routers/start.py:305)

**quick_wp_choice_kb()** (keyboards/publish.py):
  - [Назад] `menu:main` -> `cb_main_menu` (routers/start.py:305)
  - [conn.identifier] `quick:cat:{category_id}:wp:{id}` -> `cb_quick_publish_target` (routers/publishing/quick.py:176)

**publish_platform_choice_kb()** (keyboards/publish.py):
  - [Назад] `category:{category_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)
  - [label] `category:{category_id}:publish:{ps}:{id}` -> ???

**keywords_main_kb()** (keyboards/publish.py):
  - [Подобрать фразы] `category:{category_id}:kw:generate` -> `cb_kw_generate_start` (routers/categories/keywords.py:161)
  - [Загрузить свои] `category:{category_id}:kw:upload` -> `cb_kw_upload_start` (routers/categories/keywords.py:466)
  - [К категории] `category:{category_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**keyword_quantity_kb()** (keyboards/publish.py):
  - [str(n)] `kw:qty:{category_id}:{n}` -> `cb_kw_quantity` (routers/categories/keywords.py:242)

**keyword_confirm_kb()** (keyboards/publish.py):
  - [Да, генерировать ({cost} токенов)] `kw:confirm` -> `cb_kw_confirm` (routers/categories/keywords.py:290)
  - [Отмена] `category:{category_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**keyword_results_kb()** (keyboards/publish.py):
  - [Сохранить] `kw:save` -> `cb_kw_save` (routers/categories/keywords.py:403)
  - [Отменить] `kw:results:cancel` -> `cb_kw_results_cancel` (routers/categories/keywords.py:439)
  - [К категории] `category:{category_id}:card` -> `cb_category_card` (routers/categories/manage.py:151)

**audit_menu_kb()** (keyboards/publish.py):
  - [label] `project:{project_id}:audit:run` -> `cb_audit_run` (routers/analysis.py:172)
  - [Анализ конкурентов] `project:{project_id}:competitor` -> `cb_competitor_start` (routers/analysis.py:254)
  - [К проекту] `project:{project_id}:card` -> `cb_project_card` (routers/projects/card.py:89)

**audit_results_kb()** (keyboards/publish.py):
  - [Перезапустить] `project:{project_id}:audit:run` -> `cb_audit_run` (routers/analysis.py:172)
  - [Анализ конкурентов] `project:{project_id}:competitor` -> `cb_competitor_start` (routers/analysis.py:254)
  - [К проекту] `project:{project_id}:card` -> `cb_project_card` (routers/projects/card.py:89)

**competitor_confirm_kb()** (keyboards/publish.py):
  - [Да, анализировать ({cost} токенов)] `comp:confirm` -> `cb_competitor_confirm` (routers/analysis.py:329)
  - [Отмена] `project:{project_id}:card` -> `cb_project_card` (routers/projects/card.py:89)

**competitor_results_kb()** (keyboards/publish.py):
  - [К проекту] `project:{project_id}:card` -> `cb_project_card` (routers/projects/card.py:89)

**scheduler_category_list_kb()** (keyboards/schedule.py):
  - [К проекту] `project:{project_id}:card` -> `cb_project_card` (routers/projects/card.py:89)
  - [name] `sched:cat:{id}` -> `cb_scheduler_platforms` (routers/publishing/scheduler.py:82)

**scheduler_platform_list_kb()** (keyboards/schedule.py):
  - [К планировщику] `project:{project_id}:scheduler` -> `cb_scheduler_categories` (routers/publishing/scheduler.py:56)
  - [text] `sched:cat:{category_id}:plt:{id}` -> `cb_schedule_start` (routers/publishing/scheduler.py:122)

**schedule_days_kb()** (keyboards/schedule.py):
  - [Готово] `sched:days:done` -> `cb_schedule_days_done` (routers/publishing/scheduler.py:191)
  - [{day_name}{marker}] `sched:day:{day_code}` -> `cb_schedule_toggle_day` (routers/publishing/scheduler.py:171)

**schedule_count_kb()** (keyboards/schedule.py):
  - [str(n)] `sched:count:{n}` -> ???

**schedule_times_kb()** (keyboards/schedule.py):
  - [Готово ({*}/{max_count})] `sched:times:done` -> `cb_schedule_times_done` (routers/publishing/scheduler.py:256)
  - [{slot}{marker}] `sched:time:{slot}` -> ???

**schedule_summary_kb()** (keyboards/schedule.py):
  - [Отключить] `schedule:{schedule_id}:toggle` -> `cb_schedule_toggle` (routers/publishing/scheduler.py:322)
  - [Удалить] `schedule:{schedule_id}:delete` -> `cb_schedule_delete` (routers/publishing/scheduler.py:376)
  - [К планировщику] `project:{project_id}:scheduler` -> `cb_scheduler_categories` (routers/publishing/scheduler.py:56)
