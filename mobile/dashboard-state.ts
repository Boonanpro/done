export type RoomState = {id:string;has_active_run?:boolean};
export function activeRooms<T extends RoomState>(rooms:T[],localRuns:string[]):T[]{
 return rooms.filter(room=>room.has_active_run||localRuns.includes(room.id));
}
export function selectedRoomIndex(rooms:RoomState[],selectedId:string|null):number{
 return Math.max(0,rooms.findIndex(room=>room.id===selectedId));
}
export function stepRoomId(rooms:RoomState[],index:number,delta:number):string|null{
 return rooms[Math.max(0,Math.min(rooms.length-1,index+delta))]?.id??null;
}
export function roomSwipe(dx:number,dy:number):number{
 return Math.abs(dx)>40&&Math.abs(dx)>Math.abs(dy)*1.3?(dx<0?1:-1):0;
}
