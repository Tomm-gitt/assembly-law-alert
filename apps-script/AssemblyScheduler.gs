/**************************************************************
 * 국회 법률안 모니터링 - Google Apps Script 실행 스케줄러
 *
 * 목적
 * - GitHub Actions의 schedule 지연을 피하고
 * - GAS가 06:30 / 07:00 / 07:30 / 08:00 KST에
 *   기존 monitor.yml workflow_dispatch를 호출
 *
 * Script Property 필요
 * - GITHUB_WORKFLOW_TOKEN
 **************************************************************/

const ASSEMBLY_SCHEDULER = {
  OWNER: 'Tomm-gitt',
  REPO: 'assembly-law-alert',
  WORKFLOW: 'monitor.yml',
  REF: 'main',
  HANDLER: 'runAssemblyScheduler',
  TIMEZONE: 'Asia/Seoul',
  INTERVAL_MINUTES: 5,
  SLOT_WINDOW_MINUTES: 10,
  PROPERTY_PREFIX: 'ASSEMBLY_WORKFLOW_DISPATCH_',
  SLOTS: [
    { hour: 6, minute: 30 },
    { hour: 7, minute: 0 },
    { hour: 7, minute: 30 },
    { hour: 8, minute: 0 },
  ],
};

function installAssemblySchedulerTrigger() {
  let removed = 0;

  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === ASSEMBLY_SCHEDULER.HANDLER) {
      ScriptApp.deleteTrigger(trigger);
      removed++;
    }
  });

  ScriptApp.newTrigger(ASSEMBLY_SCHEDULER.HANDLER)
    .timeBased()
    .everyMinutes(ASSEMBLY_SCHEDULER.INTERVAL_MINUTES)
    .create();

  const result = diagnoseAssemblyScheduler();
  result.removedOldTriggers = removed;
  Logger.log(JSON.stringify(result));
  return result;
}

function runAssemblyScheduler() {
  const slot = getCurrentAssemblySchedulerSlot_();

  if (!slot) {
    return {
      ok: true,
      skipped: true,
      reason: 'OUTSIDE_SLOT',
    };
  }

  const props = PropertiesService.getScriptProperties();
  const propertyKey = ASSEMBLY_SCHEDULER.PROPERTY_PREFIX + slot.key;

  if (props.getProperty(propertyKey) === 'DONE') {
    return {
      ok: true,
      skipped: true,
      reason: 'ALREADY_DISPATCHED',
      slot: slot.label,
    };
  }

  const dispatchResult = dispatchAssemblyWorkflow_();

  if (dispatchResult.ok) {
    props.setProperty(propertyKey, 'DONE');
  }

  const result = {
    ok: dispatchResult.ok,
    slot: slot.label,
    dispatchResult: dispatchResult,
  };

  Logger.log(JSON.stringify(result));
  return result;
}

function testDispatchAssemblyMonitorNow() {
  const result = dispatchAssemblyWorkflow_();
  Logger.log(JSON.stringify(result));
  return result;
}

function diagnoseAssemblyScheduler() {
  const triggerCount = ScriptApp.getProjectTriggers().filter(function(trigger) {
    return trigger.getHandlerFunction() === ASSEMBLY_SCHEDULER.HANDLER;
  }).length;

  const tokenExists = !!String(
    PropertiesService.getScriptProperties().getProperty('GITHUB_WORKFLOW_TOKEN') || ''
  ).trim();

  const slot = getCurrentAssemblySchedulerSlot_();

  const result = {
    ok: triggerCount === 1 && tokenExists,
    triggerCount: triggerCount,
    configuredIntervalMinutes: ASSEMBLY_SCHEDULER.INTERVAL_MINUTES,
    tokenConfigured: tokenExists,
    currentSlot: slot ? slot.label : '',
    slots: ASSEMBLY_SCHEDULER.SLOTS.map(function(x) {
      return String(x.hour).padStart(2, '0') + ':' + String(x.minute).padStart(2, '0');
    }),
  };

  Logger.log(JSON.stringify(result));
  return result;
}

function getCurrentAssemblySchedulerSlot_() {
  const now = new Date();
  const dateKey = Utilities.formatDate(
    now,
    ASSEMBLY_SCHEDULER.TIMEZONE,
    'yyyyMMdd'
  );

  const hour = Number(
    Utilities.formatDate(now, ASSEMBLY_SCHEDULER.TIMEZONE, 'H')
  );

  const minute = Number(
    Utilities.formatDate(now, ASSEMBLY_SCHEDULER.TIMEZONE, 'm')
  );

  const nowMinutes = hour * 60 + minute;

  for (let i = ASSEMBLY_SCHEDULER.SLOTS.length - 1; i >= 0; i--) {
    const slot = ASSEMBLY_SCHEDULER.SLOTS[i];
    const slotMinutes = slot.hour * 60 + slot.minute;

    if (
      nowMinutes >= slotMinutes &&
      nowMinutes < slotMinutes + ASSEMBLY_SCHEDULER.SLOT_WINDOW_MINUTES
    ) {
      const hh = String(slot.hour).padStart(2, '0');
      const mm = String(slot.minute).padStart(2, '0');

      return {
        key: dateKey + '_' + hh + mm,
        label: hh + ':' + mm,
      };
    }
  }

  return null;
}

function dispatchAssemblyWorkflow_() {
  const token = String(
    PropertiesService.getScriptProperties().getProperty('GITHUB_WORKFLOW_TOKEN') || ''
  ).trim();

  if (!token) {
    throw new Error('Script Property GITHUB_WORKFLOW_TOKEN이 없습니다.');
  }

  const url =
    'https://api.github.com/repos/' +
    encodeURIComponent(ASSEMBLY_SCHEDULER.OWNER) + '/' +
    encodeURIComponent(ASSEMBLY_SCHEDULER.REPO) +
    '/actions/workflows/' +
    encodeURIComponent(ASSEMBLY_SCHEDULER.WORKFLOW) +
    '/dispatches';

  const payload = {
    ref: ASSEMBLY_SCHEDULER.REF,
    inputs: {
      force_send_recent: 'false',
      force_send_status_test: 'false',
    },
  };

  const waits = [0, 3000, 7000];
  let lastError = '';

  for (let i = 0; i < waits.length; i++) {
    if (waits[i] > 0) Utilities.sleep(waits[i]);

    try {
      const response = UrlFetchApp.fetch(url, {
        method: 'post',
        contentType: 'application/json',
        payload: JSON.stringify(payload),
        headers: {
          Authorization: 'Bearer ' + token,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': 'assembly-law-alert-gas-scheduler',
        },
        muteHttpExceptions: true,
      });

      const code = response.getResponseCode();
      const body = response.getContentText();

      if (code === 204) {
        return {
          ok: true,
          statusCode: code,
          attempt: i + 1,
        };
      }

      lastError = 'HTTP ' + code + (body ? ': ' + body : '');

      if (code !== 429 && code < 500) {
        break;
      }
    } catch (err) {
      lastError = String(err && err.message ? err.message : err);
    }
  }

  throw new Error('GitHub workflow dispatch 실패: ' + lastError);
}
