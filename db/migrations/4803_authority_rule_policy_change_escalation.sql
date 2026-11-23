-- K8: a policy change escalates like other T2 actions, to command + compliance (sgw.approval.policy_data).
UPDATE authority_rule SET escalated_functions = '{command,compliance}' WHERE action_type = 'policy_change';
