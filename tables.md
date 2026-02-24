MyPet:
name
breed
birth_date
gender
castrated
allergies（String）
chronic_conditions（String）


Event:
event_id
pet_id
date(YYYY-MM-DD)
type（healthCheck/vaccine/diagnosis/symptoms/surgery/treatment）
vet
title（一句话）
note（description）
attachment_path（可选）


Measurement:
date
type（weight/neck/chest/waist）
value
unit
note



Medication:
drug_name
dose
unit
frequency
start_date
end_date
reason
note


Reminder:
due_date
title
note
status（pending/done）
repeat_rule（先留空，后面再做重复）


episodes 
id
pet_id
condition_name_zh（如：二尖瓣返流B1 / 慢性支原体感染 / 腰椎间盘问题）
condition_name_en（可选）
category（cardiac/respiratory/ortho/neuro/skin/other）
status（active/resolved/monitoring）
start_date
end_date（可空）
note


attachments:
id, event_id (FK)
file_path (本地路径) / 或存储为相对路径
mime_type, original_name
sha256（可选，但很好用）
created_at