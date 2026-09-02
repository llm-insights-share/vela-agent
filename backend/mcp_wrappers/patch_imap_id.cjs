/**
 * NetEase 163/126 IMAP requires RFC 2971 ID after LOGIN; otherwise SELECT/EXAMINE
 * returns "Unsafe Login". mcp-mail-server (node-imap) does not send ID — patch openBox.
 */
'use strict';

const Module = require('module');

function sendImapId(imap, cb) {
  if (!imap || typeof imap._enqueue !== 'function') {
    return cb();
  }
  if (imap.__velaIdSent) {
    return cb();
  }
  imap._enqueue(
    'ID ("name" "vela-agent" "version" "1.0.0" "vendor" "vela" "support-email" "support@vela.local")',
    function () {
      imap.__velaIdSent = true;
      cb();
    }
  );
}

function patchImapExport(exported) {
  if (!exported) return exported;
  const proto = exported.prototype;
  if (!proto || typeof proto.openBox !== 'function') return exported;
  if (proto.__velaIdPatched) return exported;
  proto.__velaIdPatched = true;
  const origOpenBox = proto.openBox;
  proto.openBox = function (name, readOnly, cb) {
    if (typeof readOnly === 'function') {
      cb = readOnly;
      readOnly = true;
    }
    const self = this;
    sendImapId(self, function () {
      return origOpenBox.call(self, name, readOnly, cb);
    });
  };
  return exported;
}

function isImapModuleId(id) {
  const sid = String(id || '');
  if (sid === 'imap') return true;
  // Absolute/relative resolves often look like .../node_modules/imap/lib/Connection.js
  return /[/\\]imap([/\\]lib[/\\]Connection)?(\.js)?$/i.test(sid);
}

const originalRequire = Module.prototype.require;
Module.prototype.require = function patchedRequire(id) {
  const exported = originalRequire.apply(this, arguments);
  if (isImapModuleId(id)) {
    try {
      return patchImapExport(exported);
    } catch (_) {
      return exported;
    }
  }
  return exported;
};

module.exports = { patchImapExport, isImapModuleId };
