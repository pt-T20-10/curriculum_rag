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
