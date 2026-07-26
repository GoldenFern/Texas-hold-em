/** Socket.IO 客户端单例（npm 打包,无 CDN 依赖）。 */

import { io, type Socket } from 'socket.io-client'
import type { ClientToServerEvents, ServerToClientEvents } from './protocol'

export type AppSocket = Socket<ServerToClientEvents, ClientToServerEvents>

let socket: AppSocket | null = null

/** 获取(或创建)全局 Socket 连接。 */
export function getSocket(): AppSocket {
  if (socket === null) {
    // 开发经 Vite 代理,生产同源直连
    socket = io({ path: '/socket.io', transports: ['websocket', 'polling'] })
  }
  return socket
}
