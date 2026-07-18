export function translateConfigGroup(groupKey, group, t) {
  return {
    ...group,
    label: t(`configRegistry.groups.${groupKey}.label`, { defaultValue: group?.label || groupKey }),
    description: t(`configRegistry.groups.${groupKey}.description`, { defaultValue: group?.description || '' }),
  }
}

export function translateConfigParam(param, t) {
  if (!param) return param

  return {
    ...param,
    label: t(`configRegistry.params.${param.key}.label`, { defaultValue: param.label || param.key }),
    description: t(`configRegistry.params.${param.key}.description`, { defaultValue: param.description || '' }),
  }
}

export function translateConfigChoice(paramKey, choice, t) {
  const labels = {
    TEXTBOOK_GENERATION_MODE: {
      user_provided_api_keys: 'Người dùng tự nhập API key',
      system_credit_billing: 'Nạp tiền bằng credit hệ thống',
    },
  }
  return t(`configRegistry.choices.${paramKey}.${choice}`, {
    defaultValue: labels[paramKey]?.[choice] || choice,
  })
}
