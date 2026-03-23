# Module keyboards/ -- Inline Keyboards

## Files
| File | LOC | Purpose |
|---|---|---|
| inline.py | 1746 | all inline keyboards (Dashboard through Admin) |
| pipeline.py | 1072 | Article/Social Pipeline keyboards + crosspost |
| pagination.py | 76 | PAGE_SIZE=8, paginate() helper, _safe_cb() (64-byte guard) |

No reply.py exists -- all keyboards are inline.

## Router -> keyboard functions
| Router | Key keyboard functions |
|---|---|
| start.py | dashboard_kb, dashboard_resume_kb, menu_kb, consent_kb |
| projects/list | project_list_kb, project_list_empty_kb |
| projects/card | project_card_kb, project_edit_kb, project_delete_confirm_kb, project_deleted_kb, project_created_kb |
| projects/content_settings | project_content_settings_kb, project_platform_card_kb, project_text_menu_kb, project_word_count_kb, project_html_style_kb, project_text_style_kb, project_image_menu_kb, project_preview_format_kb, project_article_format_kb, project_image_style_kb, project_image_count_kb, project_text_on_image_kb, project_camera_kb, project_angle_kb, project_quality_kb, project_tone_kb |
| categories/manage | category_list_kb, category_list_empty_kb, category_card_kb, category_delete_confirm_kb, category_created_kb |
| categories/keywords | keywords_empty_kb, keywords_summary_kb, keywords_cluster_list_kb, keywords_cluster_delete_list_kb, keywords_results_kb, keywords_delete_all_confirm_kb |
| categories/description | description_kb, description_review_kb |
| categories/prices | prices_kb |
| platforms/connections | connection_list_kb, connection_manage_kb, connection_delete_confirm_kb |
| profile | profile_kb, notifications_kb, referral_kb, delete_account_confirm_kb, delete_account_cancelled_kb |
| tariffs | tariffs_kb, payment_method_kb, yookassa_link_kb |
| scheduler | scheduler_type_kb, scheduler_cat_list_kb, scheduler_social_cat_list_kb, scheduler_conn_list_kb, scheduler_config_kb, schedule_days_kb, schedule_count_kb, scheduler_social_conn_list_kb, scheduler_crosspost_kb, scheduler_social_config_kb, schedule_times_kb |
| pipeline (article) | pipeline_projects_kb, pipeline_no_projects_kb, pipeline_no_wp_kb, pipeline_categories_kb, pipeline_no_categories_kb, pipeline_readiness_kb, pipeline_confirm_kb, pipeline_insufficient_balance_kb, pipeline_preview_kb, pipeline_preview_no_wp_kb, pipeline_result_kb, pipeline_generation_error_kb, pipeline_exit_confirm_kb |
| pipeline (readiness) | pipeline_keywords_options_kb, pipeline_keywords_city_kb, pipeline_description_options_kb, pipeline_prices_options_kb, pipeline_images_options_kb, pipeline_back_to_checklist_kb |
| pipeline (social) | social_connections_kb, social_no_connections_kb, social_readiness_kb, social_exit_confirm_kb, social_confirm_kb, social_insufficient_balance_kb, social_review_kb, social_result_kb, crosspost_select_kb, crosspost_result_kb |
| admin | admin_panel_kb, user_actions_kb, broadcast_audience_kb, broadcast_confirm_kb |

## Shared utilities
- `cancel_kb(callback_data)` -- universal cancel button (default "fsm:cancel")
- `format_connection_display(conn)` -- shared formatting for connection display
- `paginate(items, page, item_cb, back_cb, page_cb)` -- generic pagination with PAGE_SIZE=8

## Conventions
- Naming: `{entity}_{action}_kb()` (e.g. `project_card_kb`, `category_list_kb`)
- ButtonStyle: PRIMARY (max 1 per screen), SUCCESS, DANGER, DEFAULT
- PAGE_SIZE=8 for paginated lists
- `_safe_cb()` truncates callback_data to 64 bytes
