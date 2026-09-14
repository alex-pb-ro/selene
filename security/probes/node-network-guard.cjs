const fs=require('fs');
function deny(kind,args){fs.appendFileSync(process.env.SELENE_NETWORK_AUDIT_LOG,JSON.stringify({kind,pid:process.pid,script:process.argv[1],args:args.map(a=>typeof a==='string'?a:typeof a==='number'?a:a&&typeof a==='object'?{hostname:a.hostname,host:a.host,path:a.path,port:a.port}:typeof a),stack:new Error().stack.split('\n').slice(1,6)})+'\n');throw new Error('External network disabled by audit');}
for(const name of ['http','https']){const m=require(name);for(const method of ['request','get'])m[method]=(...args)=>deny(name+'.'+method,args);}
require('net').Socket.prototype.connect=function(...args){return deny('net.connect',args)};
require('tls').connect=(...args)=>deny('tls.connect',args);
const dns=require('dns');for(const key of ['lookup','resolve','resolve4','resolve6'])dns[key]=(...args)=>deny('dns.'+key,args);
globalThis.fetch=(...args)=>deny('fetch',args);
