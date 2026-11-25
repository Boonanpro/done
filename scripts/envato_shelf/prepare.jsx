// Runs only in the separate After Effects instance opened for this render.
(function () {
    var p = app.project, job = DAN_SHELF_JOB, spec = job.item;
    var report = new File(job.report);
    function writeStatus(value) {
        report.encoding = "UTF-8"; report.open("w"); report.write(value); report.close();
    }
    function getComp(id) {
        var c = p.itemByID(id);
        if (!(c instanceof CompItem)) throw Error("コンポジションが見つかりません: " + id);
        return c;
    }
    function setPhoto(c, path) {
        var file = new File(path);
        if (!file.exists) throw Error("写真が見つかりません");
        var photo = p.importFile(new ImportOptions(file)), layer = c.layers.add(photo);
        var size = 100 * Math.max(c.width / photo.width, c.height / photo.height);
        layer.property("ADBE Transform Group").property("ADBE Scale").setValue([size, size]);
        for (var i = 2; i <= c.numLayers; i++) c.layer(i).enabled = false;
    }
    function repair(group) {
        for (var i = 1; i <= group.numProperties; i++) {
            var prop = group.property(i);
            if (prop.propertyType !== PropertyType.PROPERTY) { repair(prop); continue; }
            if (!prop.canSetExpression || !prop.expression) continue;
            var fixed = prop.expression.replace(/\(["'](Slider|Color|Checkbox|Angle|Point|3D Point|Layer|Menu)["']\)/g, "(1)");
            if (fixed !== prop.expression) prop.expression = fixed;
        }
    }
    try {
        var source = getComp(spec.comp);
        if (source.name !== spec.compName) throw Error("テンプレートの版と差し替え先が一致しません");
        if (job.repair) {
            for (var i = 1; i <= p.numItems; i++) {
                var c = p.item(i);
                if (c instanceof CompItem) for (var j = 1; j <= c.numLayers; j++) repair(c.layer(j));
            }
        }
        for (var i = 0; i < spec.fields.length; i++) {
            var field = spec.fields[i], value = job.values[i];
            for (var j = 0; j < field.targets.length; j++) {
                var target = field.targets[j];
                if (field.type === "photo" || field.type === "photos") {
                    setPhoto(getComp(target), field.type === "photo" ? value : value[j % value.length]);
                } else {
                    var layer = getComp(target[0]).layer(target[1]);
                    if (field.type === "number") {
                        layer.property("ADBE Effect Parade").property("End Number").property(1).setValue(value);
                    } else {
                        var text = layer.property("ADBE Text Properties").property("ADBE Text Document");
                        var doc = text.value;
                        var oldName = layer.name;
                        doc.text = value; doc.font = job.font;
                        if (spec.textColor) { doc.applyFill = true; doc.fillColor = spec.textColor; }
                        text.setValue(doc); layer.name = oldName;
                        if (text.value.font !== job.font) throw Error("指定書体を使えません: " + job.font);
                    }
                }
            }
        }
        if (job.font && app.fonts.getFontsByPostScriptName(job.font).length === 0)
            throw Error("After Effects で書体が見つかりません: " + job.font);
        var width = job.width, height = Math.round(width * source.height / source.width / 2) * 2;
        var wrap = p.items.addComp("Dan Component", width, height, 1, spec.duration, job.fps);
        var nested = wrap.layers.add(source);
        nested.startTime = -spec.start;
        var scale = 100 * width / source.width * (spec.scale || 1);
        nested.property("ADBE Transform Group").property("ADBE Scale").setValue([scale, scale]);
        if (spec.position) nested.property("ADBE Transform Group").property("ADBE Position").setValue([width*spec.position[0],height*spec.position[1]]);
        if (spec.inputWhite) {
            p.bitsPerChannel = 16;
            nested.property("ADBE Effect Parade").addProperty("ADBE Easy Levels2").property(4).setValue(spec.inputWhite);
        }
        if (spec.background) wrap.layers.addSolid(spec.background,"背景",width,height,1,spec.duration).moveToEnd();
        if (spec.wipePeak) {
            nested.timeRemapEnabled = true;
            var t = nested.property("ADBE Time Remapping");
            while(t.numKeys > 1) t.removeKey(t.numKeys);
            t.setValueAtTime(0,0);
            t.setValueAtTime(spec.duration/2,spec.wipePeak);
            t.setValueAtTime(spec.duration,0);
        }
        if (nested.hasAudio) nested.audioEnabled = false;
        if(job.mode === "preview"){
            for(var frame=0;frame<job.frames;frame++) {
                var suffix = ("0000"+frame).slice(-4);
                wrap.saveFrameToPng(frame*spec.duration/job.frames,new File(job.folder+"/"+suffix+".png"));
            }
        } else {
            for(var k=p.renderQueue.numItems;k>=1;k--) p.renderQueue.item(k).remove();
            var queue = p.renderQueue.items.add(wrap), module=queue.outputModule(1);
            var names=module.templates, template="";
            for(var k=0;k<names.length;k++) if(names[k]==="アルファ付き高品質" || names[k]==="High Quality with Alpha") template=names[k];
            if(!template) throw Error("アルファ付きの書き出し設定がありません");
            module.applyTemplate(template);
            module.file = new File(job.output);
            p.save(new File(job.project));
        }
        writeStatus("ok");
    } catch (e) { writeStatus("行 "+e.line+" "+e.toString()); }
})();
