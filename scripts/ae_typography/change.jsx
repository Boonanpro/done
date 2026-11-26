(function () {
    var job = DAN_TEXT_JOB;
    var status = new File(job.report);
    function finish(value) {
        status.encoding = "UTF-8"; status.open("w"); status.write(value); status.close();
    }
    try {
        app.beginSuppressDialogs();
        var project = app.open(new File(job.project)), comp = null;
        for (var i = 1; i <= project.numItems; i++) {
            var item = project.item(i);
            if (item instanceof CompItem && item.name === job.comp) { comp = item; break; }
        }
        if (!comp) throw Error("元のコンポジションがありません");
        for (var k=0; k<job.fields.length; k++) {
            var field=job.fields[k], hits=0;
            var original=field.vertical ? field.text.split("").join("\r") : field.text;
            var replacement=field.vertical ? job.values[k].split("").join("\r") : job.values[k].replace(/\n/g,"\r");
            for (var n=1;n<=comp.numLayers;n++) {
                var layer=comp.layer(n);
                var group=layer.property("ADBE Text Properties");
                if (!group) continue;
                var prop=group.property("ADBE Text Document"), doc=prop.value;
                if (doc.text!==original || (field.at!==undefined && Math.abs(layer.inPoint-field.at)>0.05)) continue;
                // Read the original values first, so a user may swap two phrases.
                if(!field.layers) field.layers=[];
                field.layers.push(n); hits++;
            }
            if (!hits) throw Error("元の文字レイヤーがありません: "+field.text);
            field.replacement=replacement;
        }
        for(var k=0;k<job.fields.length;k++){
            var field=job.fields[k];
            if(field.text===job.values[k]) continue;
            for(var j=0;j<field.layers.length;j++){
                var layer=comp.layer(field.layers[j]), tp=layer.property("ADBE Text Properties").property("ADBE Text Document");
                var doc=tp.value; doc.text=field.replacement; tp.setValue(doc);
                var rect=layer.sourceRectAtTime(Math.max(0,layer.inPoint),false);
                layer.transform.anchorPoint.setValue([rect.left+rect.width/2,rect.top+rect.height/2]);
            }
        }
        if(job.still){
            var img=new File(job.output); comp.saveFrameToPng(0,img);
            for (var w=0;w<300 && !img.exists;w++) $.sleep(100);
            if(!img.exists) throw Error("文字の画像を作れませんでした");
        } else {
            for(var q=project.renderQueue.numItems;q>=1;q--) project.renderQueue.item(q).remove();
            var om=project.renderQueue.items.add(comp).outputModule(1), templates=om.templates, tpl="";
            for(var n=0;n<templates.length;n++) if(templates[n]==="アルファ付き高品質"||templates[n]==="High Quality with Alpha") tpl=templates[n];
            if(!tpl) throw Error("透明な映像の設定がありません");
            om.applyTemplate(tpl); om.file=new File(job.output); project.save(new File(job.workingProject));
        }
        finish("ok");
    }catch(e){finish("文字の描画に失敗しました。"+e.toString());}
})();
