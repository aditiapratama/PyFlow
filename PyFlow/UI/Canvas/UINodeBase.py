"""@file Node.py

Node is a base class for all ui nodes. This is actually a QGraphicsItem with all common stuff for nodes.

Also, it implements [initializeFromFunction](@ref PyFlow.Core.Node.initializeFromFunction) method which constructs node from given annotated function.
@sa FunctionLibrary.py
"""

import weakref
from multipledispatch import dispatch
from nine import str

from Qt import QtCore
from Qt import QtGui
from Qt.QtWidgets import QGraphicsTextItem
from Qt.QtWidgets import QGraphicsItem
from Qt.QtWidgets import QGraphicsObject
from Qt.QtWidgets import QLabel
from Qt.QtWidgets import QTextBrowser
from Qt.QtWidgets import QGraphicsWidget
from Qt.QtWidgets import QGraphicsLinearLayout
from Qt.QtWidgets import QSizePolicy
from Qt.QtWidgets import QLineEdit
from Qt.QtWidgets import QApplication
from Qt.QtWidgets import QColorDialog
from Qt.QtWidgets import QMenu

from PyFlow.UI.Utils.Settings import *
from PyFlow.UI.Canvas.UIPinBase import (
    UIPinBase,
    getUIPinInstance,
    UIGroupPinBase
)
from PyFlow.UI.Canvas.UICommon import VisibilityPolicy
from PyFlow.UI.Widgets.InputWidgets import createInputWidget
from PyFlow.UI.Canvas.Painters import NodePainter
from PyFlow.UI.Widgets.EditableLabel import EditableLabel
from PyFlow.UI.Widgets.PropertiesFramework import CollapsibleFormWidget, PropertiesWidget
from PyFlow.UI.UIInterfaces import IPropertiesViewSupport
from PyFlow.Core.NodeBase import NodeBase
from PyFlow.Core.Common import *

from collections import OrderedDict

UI_NODES_FACTORIES = {}


class NodeName(QGraphicsWidget):
    """docstring for NodeName"""
    def __init__(self, parent=None):
        super(NodeName, self).__init__(parent)
        self.setAcceptHoverEvents(True)
        self.setGraphicsItem(self)
        self.hovered = False

    def IsRenamable(self):
        return False

    def hoverEnterEvent(self, event):
        super(NodeName, self).hoverEnterEvent(event)
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        super(NodeName, self).hoverLeaveEvent(event)
        self.hovered = False
        self.update()

    def sizeHint(self, which, constraint):
        font = self.parentItem().nodeNameFont
        textWidth = QtGui.QFontMetrics(font).width(self.parentItem().displayName)
        textHeight = QtGui.QFontMetrics(font).height()
        return QtCore.QSizeF(textWidth, textHeight)

    def setGeometry(self, rect):
        self.prepareGeometryChange()
        super(QGraphicsWidget, self).setGeometry(rect)
        self.setPos(rect.topLeft())

    def paint(self, painter, option, widget):
        lod = self.parentItem().canvasRef().getLodValueFromCurrentScale(3)
        frame = QtCore.QRectF(QtCore.QPointF(0, 0), self.geometry().size())

        if lod < 3:
            text = self.parentItem().displayName
            painter.setFont(self.parentItem().nodeNameFont)
            painter.setPen(QtGui.QPen(self.parentItem().labelTextColor, 0.5))
            width = QtGui.QFontMetrics(painter.font()).width(text)
            height = QtGui.QFontMetrics(painter.font()).height()
            yCenter = (frame.height() / 2) + (height / 2.5)
            x = 3
            painter.drawText(x, yCenter, text)


class UINodeBase(QGraphicsWidget, IPropertiesViewSupport):
    """
    Default node description
    """
    # Event called when node name changes
    displayNameChanged = QtCore.Signal(str)

    def __init__(self, raw_node, w=80, color=Colors.NodeBackgrounds, headColor=Colors.NodeNameRectGreen, bUseTextureBg=True):
        super(UINodeBase, self).__init__()
        self.setFlag(QGraphicsWidget.ItemIsMovable)
        self.setFlag(QGraphicsWidget.ItemIsFocusable)
        self.setFlag(QGraphicsWidget.ItemIsSelectable)
        self.setFlag(QGraphicsWidget.ItemSendsGeometryChanges)
        # self.setFlag(QGraphicsWidget.ItemSendsScenePositionChanges)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        # self.setZValue(1)
        self._rawNode = raw_node
        self._rawNode.setWrapper(self)
        self._rawNode.killed.connect(self.kill)
        self._rawNode.tick.connect(self.Tick)
        self.opt_node_base_color = Colors.NodeBackgrounds
        self.opt_selected_pen_color = Colors.NodeSelectedPenColor
        self.opt_pen_selected_type = QtCore.Qt.SolidLine
        self.labelHeight = 15
        self._left_stretch = 0
        self.color = color
        self.drawlabel = True
        self.headColor = headColor
        self.height_offset = 3
        self._w = 0
        self.h = 40
        self.bUseTextureBg = bUseTextureBg  # self.canvasRef().styleSheetEditor.USETEXTUREBG
        self.custom_widget_data = {}
        # node name
        self._displayName = self.name

        # GUI Layout
        self._labelTextColor = QtCore.Qt.white
        self.nodeLayout = QGraphicsLinearLayout(QtCore.Qt.Vertical)
        self.nodeLayout.setContentsMargins(3, 3, 3, 3)
        self.nodeLayout.setSpacing(10)
        self.nodeNameFont = QtGui.QFont("Consolas")
        self.nodeNameFont.setPointSize(6)
        self.nodeNameWidget = NodeName(self)
        self.nodeLayout.addItem(self.nodeNameWidget)
        self.nodeLayout.setStretchFactor(self.nodeNameWidget, 1)
        self.pinsLayout = QGraphicsLinearLayout(QtCore.Qt.Horizontal)
        self.pinsLayout.setContentsMargins(0, 0, 0, 0)
        self.nodeLayout.addItem(self.pinsLayout)
        self.nodeLayout.setStretchFactor(self.pinsLayout, 2)
        self.inputsLayout = QGraphicsLinearLayout(QtCore.Qt.Vertical)
        self.inputsLayout.setContentsMargins(0, 0, 0, 0)
        self.outputsLayout = QGraphicsLinearLayout(QtCore.Qt.Vertical)
        self.outputsLayout.setContentsMargins(0, 0, 0, 0)
        self.pinsLayout.addItem(self.inputsLayout)
        self.pinsLayout.addItem(self.outputsLayout)
        self.setLayout(self.nodeLayout)

        self.icon = None
        self.canvasRef = None
        self._menu = QMenu()

        # Resizing Options
        self.minWidth = 25
        self.minHeight = self.h
        self.initialRectWidth = 0.0
        self.initialRectHeight = 0.0
        self.expanded = True
        self.resizable = False
        self.bResize = False
        self.resizeDirection = (0, 0)
        self.lastMousePos = QtCore.QPointF()

        # Hiding/Moving By Group/collapse/By Pin
        self.nodesToMove = {}
        self.edgesToHide = []
        self.nodesNamesToMove = []
        self.pinsToMove = {}
        self._rect = self.childrenBoundingRect()

        # Group Pins
        self.inputGroupPins = {}
        self.outputGroupPins = {}

        # Core Nodes Support
        self.isTemp = False
        self.isCommentNode = False

    @property
    def labelTextColor(self):
        return self._labelTextColor

    @labelTextColor.setter
    def labelTextColor(self, value):
        self._labelTextColor = value
        self.nodeNameWidget.color = value

    def __repr__(self):
        graphName = self._rawNode.graph().name if self._rawNode.graph is not None else str(None)
        return "class[{0}];name[{1}];graph[{2}]".format(self.__class__.__name__, self.getName(), graphName)

    def sizeHint(self, which, constraint):
        size = self.childrenBoundingRect().size()
        textWidth = QtGui.QFontMetrics(self.nodeNameFont).width(self.displayName)
        if size.width() < textWidth:
            size.setWidth(textWidth)
        return size + QtCore.QSizeF(6, 6)

    def setGeometry(self, rect):
        self.prepareGeometryChange()
        super(QGraphicsWidget, self).setGeometry(rect)
        self.setPos(rect.topLeft())

    @property
    def uid(self):
        return self._rawNode._uid

    @uid.setter
    def uid(self, value):
        self._rawNode._uid = value

    @property
    def name(self):
        return self._rawNode.name

    @name.setter
    def name(self, value):
        self._rawNode.setName(value)

    @property
    def displayName(self):
        return self._displayName

    @displayName.setter
    def displayName(self, value):
        self._displayName = value
        self.displayNameChanged.emit(self._displayName)

    @property
    def pins(self):
        return self._rawNode.pins

    @property
    def UIPins(self):
        result = OrderedDict()
        for rawPin in self._rawNode.pins:
            uiPinRef = rawPin.getWrapper()
            if uiPinRef is not None:
                result[rawPin.uid] = uiPinRef()
        return result

    @property
    def UIinputs(self):
        result = OrderedDict()
        for rawPin in self._rawNode.pins:
            if rawPin.direction == PinDirection.Input:
                result[rawPin.uid] = rawPin.getWrapper()()
        return result

    @property
    def UIoutputs(self):
        result = OrderedDict()
        for rawPin in self._rawNode.pins:
            if rawPin.direction == PinDirection.Output:
                result[rawPin.uid] = rawPin.getWrapper()()
        return result

    @property
    def namePinOutputsMap(self):
        result = OrderedDict()
        for rawPin in self._rawNode.pins:
            if rawPin.direction == PinDirection.Output:
                result[rawPin.name] = rawPin.getWrapper()()
        return result

    @property
    def namePinInputsMap(self):
        result = OrderedDict()
        for rawPin in self._rawNode.pins:
            if rawPin.direction == PinDirection.Input:
                result[rawPin.name] = rawPin.getWrapper()()
        return result

    @property
    def w(self):
        return self._w

    @w.setter
    def w(self, value):
        self._w = value

    def getName(self):
        return self._rawNode.getName()

    def setName(self, name):
        self._rawNode.setName(name)

    def getPin(self, name, pinsGroup=PinSelectionGroup.BothSides):
        pin = self._rawNode.getPin(name, pinsGroup)
        if pin is not None:
            if pin.getWrapper() is not None:
                return pin.getWrapper()()
        return None

    @staticmethod
    def removePinByName(node, name):
        pin = node.getPin(name)
        if pin:
            pin.kill()

    @staticmethod
    def recreate(node):
        templ = node.serialize()
        uid = node.uid
        node.kill()
        newNode = node.canvas.createNode(templ)
        newNode.uid = uid
        return newNode

    @staticmethod
    def jsonTemplate():
        template = {}
        template['meta'] = {}
        return template

    @property
    def isCompoundNode(self):
        return self._rawNode.isCompoundNode

    # TODO: add this to ui node interface
    def serializationHook(self):
        # this will be called by raw node
        # to gather ui specific info
        template = self.jsonTemplate()
        if self.resizable:
            template['meta']['resize'] = {'w': self._rect.right(), 'h': self._rect.bottom()}
        template['displayName'] = self.displayName
        return template

    def serialize(self):
        return self._rawNode.serialize()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            self._rawNode.setPosition(value.x(), value.y())
        return super(UINodeBase, self).itemChange(change, value)

    def autoAffectPins(self):
        self._rawNode.autoAffectPins()

    def postCreate(self, jsonTemplate=None):
        # create ui pin wrappers
        for i in self._rawNode.getOrderedPins():
            self._createUIPinWrapper(i)

        self.updateNodeShape(label=jsonTemplate['meta']['label'])
        self.setPos(self._rawNode.x, self._rawNode.y)

        if self.canvasRef().graphManager.activeGraph() != self._rawNode.graph():
            self.hide()

        if self._rawNode.isCallable():
            self.headColor = Colors.NodeNameRectBlue

        if not self.drawlabel:
            self.nodeNameWidget.hide()

    def isCallable(self):
        return self._rawNode.isCallable()

    def category(self):
        return self._rawNode.category()

    def description(self):
        return self._rawNode.description()

    @property
    def packageName(self):
        return self._rawNode.packageName

    def getData(self, pinName):
        if pinName in [p.name for p in self.inputs.values()]:
            p = self.getPin(pinName, PinSelectionGroup.Inputs)
            return p.getData()

    def setData(self, pinName, data):
        if pinName in [p.name for p in self.outputs.values()]:
            p = self.getPin(pinName, PinSelectionGroup.Outputs)
            p.setData(data)

    def getPinsWidth(self):
        iwidth = 0
        owidth = 0
        pinwidth = 0
        pinwidth2 = 0
        for i in self.UIPins.values():
            if i.direction == PinDirection.Input:
                iwidth = max(iwidth, QtGui.QFontMetricsF(i._label().font()).width(i.displayName()))
                pinwidth = max(pinwidth, i.width)
            else:
                owidth = max(owidth, QtGui.QFontMetricsF(i._label().font()).width(i.displayName()))
                pinwidth2 = max(pinwidth2, i.width)
        return iwidth + owidth + pinwidth + pinwidth2 + Spacings.kPinOffset

    def updateNodeShape(self, label=None):
        self.updateGeometry()
        self.setToolTip(self.description())
        self.update()

    def onChangeColor(self, label=False):
        res = QColorDialog.getColor(self.color, None, 'Node color setup')
        if res.isValid():
            res.setAlpha(80)
            self.color = res
            if label:
                # self.label().color = res
                self.update()
                # self.label().update()

    def translate(self, x, y, moveChildren=False):
        if moveChildren:
            for n in self.nodesToMove:
                if not n.isSelected():
                    n.translate(x, y)
        super(UINodeBase, self).moveBy(x, y)

    def paint(self, painter, option, widget):
        NodePainter.default(self, painter, option, widget)
        # painter.setBrush(QtGui.QColor(100, 100, 100))
        # painter.drawRoundedRect(self.boundingRect(), 5, 5)
        # painter.drawRoundedRect(self.mapFromParent(self.geometry()).boundingRect(), 5, 5)

    def shouldResize(self, cursorPos):
        cursorPos = self.mapFromScene(cursorPos)
        margin = 4
        rect = self.boundingRect()
        pBottomRight = rect.bottomRight()
        pBottomLeft = rect.bottomLeft()
        bottomRightRect = QtCore.QRectF(
            pBottomRight.x() - margin, pBottomRight.y() - margin, margin, margin)
        bottomLeftRect = QtCore.QRectF(
            pBottomLeft.x(), pBottomLeft.y() - margin, 5, 5)
        result = {"resize": False, "direction": self.resizeDirection}
        if bottomRightRect.contains(cursorPos):
            result["resize"] = True
            result["direction"] = (1, -1)
        elif bottomLeftRect.contains(cursorPos):
            result["resize"] = True
            result["direction"] = (-1, -1)
        elif cursorPos.x() > (rect.width() - margin):
            result["resize"] = True
            result["direction"] = (1, 0)
        elif cursorPos.y() > (rect.bottom() - margin):
            result["resize"] = True
            result["direction"] = (0, -1)
        elif cursorPos.x() < (rect.x() + margin):
            result["resize"] = True
            result["direction"] = (-1, 0)
        return result

    def contextMenuEvent(self, event):
        self._menu.exec_(event.screenPos())

    def mousePressEvent(self, event):
        self.update()
        super(UINodeBase, self).mousePressEvent(event)
        self.mousePressPos = event.scenePos()
        self.origPos = self.pos()
        self.initPos = self.pos()
        self.initialRect = self.boundingRect()
        if self.expanded and self.resizable:
            resizeOpts = self.shouldResize(self.mapToScene(event.pos()))
            if resizeOpts["resize"]:
                self.resizeDirection = resizeOpts["direction"]
                self.initialRectWidth = self.initialRect.width()
                self.initialRectHeight = self.initialRect.height()
                self.setFlag(QGraphicsItem.ItemIsMovable, False)
                self.bResize = True

    def mouseMoveEvent(self, event):
        super(UINodeBase, self).mouseMoveEvent(event)
        # resize
        if self.bResize:
            delta = event.scenePos() - self.mousePressPos
            if self.resizeDirection == (1, 0):
                # right connection resize
                newWidth = delta.x() + self.initialRectWidth
                if newWidth > self.minWidth:
                    # self.label().width = newWidth
                    self._rect.setWidth(newWidth)
                    self.w = newWidth
            elif self.resizeDirection == (-1, 0):
                # left connection resize
                posdelta = self.mapToScene(event.pos()) - self.origPos
                posdelta2 = self.mapToScene(event.pos()) - self.initPos
                newWidth = -posdelta2.x() + self.initialRectWidth
                if newWidth > self.minWidth:
                    self.translate(posdelta.x(), 0, False)
                    self.origPos = self.pos()
                    # self.label().width = newWidth
                    self._rect.setWidth(newWidth)
                    self.w = newWidth
            elif self.resizeDirection == (0, -1):
                newHeight = delta.y() + self.initialRectHeight
                # newHeight = max(newHeight, self.label().h + 20.0)
                if newHeight > self.minHeight:
                    # bottom connection resize
                    self._rect.setHeight(newHeight)
            elif self.resizeDirection == (1, -1):
                newWidth = delta.x() + self.initialRectWidth
                newHeight = delta.y() + self.initialRectHeight
                # newHeight = max(newHeight, self.label().h + 20.0)
                if newWidth > self.minWidth:
                    # self.label().width = newWidth
                    self._rect.setWidth(newWidth)
                    self.w = newWidth
                if newHeight > self.minHeight:
                    self._rect.setHeight(newHeight)
            elif self.resizeDirection == (-1, -1):
                posdelta2 = self.mapToScene(event.pos()) - self.initPos
                newWidth = -posdelta2.x() + self.initialRectWidth
                newHeight = delta.y() + self.initialRectHeight
                # newHeight = max(newHeight, self.label().h + 20.0)
                posdelta = event.scenePos() - self.origPos
                if newWidth > self.minWidth:  # and newWidth > self.minWidth:
                    self.translate(posdelta.x(), 0, False)
                    self.origPos = self.pos()
                    # self.label().width = newWidth
                    self._rect.setWidth(newWidth)
                    self.w = newWidth
                if newHeight > self.minHeight:
                    self._rect.setHeight(newHeight)
            # self.nodeMainGWidget.setGeometry(QtCore.QRectF(
            #     0, 0, self.w, self.boundingRect().height()))
            self.update()
            # self.label().update()
        self.lastMousePos = event.pos()

    def mouseReleaseEvent(self, event):
        self.update()
        self.bResize = False
        super(UINodeBase, self).mouseReleaseEvent(event)

    def clone(self):
        templ = self.serialize()
        templ['name'] = self.name
        templ['uuid'] = str(uuid.uuid4())
        for inp in templ['inputs']:
            inp['uuid'] = str(uuid.uuid4())
        for out in templ['outputs']:
            out['uuid'] = str(uuid.uuid4())
        new_node = self.canvasRef().createNode(templ)
        return new_node

    def call(self, name):
        self._rawNode.call(name)

    def createPropertiesWidget(self, propertiesWidget):
        baseCategory = CollapsibleFormWidget(headName="Base")

        le_name = QLineEdit(self.getName())
        le_name.setReadOnly(True)
        # if self.label().IsRenamable():
        #     le_name.setReadOnly(False)
        #     le_name.returnPressed.connect(lambda: self.setName(le_name.text()))
        baseCategory.addWidget("Name", le_name)

        leUid = QLineEdit(str(self._rawNode.graph().name))
        leUid.setReadOnly(True)
        baseCategory.addWidget("Owning graph", leUid)

        text = "{0}".format(self.packageName)
        if self._rawNode.lib:
            text += " | {0}".format(self._rawNode.lib)
        text += " | {0}".format(self._rawNode.__class__.__name__)
        leType = QLineEdit(text)
        leType.setReadOnly(True)
        baseCategory.addWidget("Type", leType)

        propertiesWidget.addWidget(baseCategory)

        # inputs
        if len([i for i in self.UIinputs.values()]) != 0:
            inputsCategory = CollapsibleFormWidget(headName="Inputs")
            sortedInputs = sorted(self.UIinputs.values(), key=lambda x: x.name)
            for inp in sortedInputs:
                if inp.isList():
                    # TODO: create list input widget
                    continue
                dataSetter = inp.call if inp.isExec() else inp.setData
                w = createInputWidget(inp.dataType, dataSetter, inp.defaultValue())
                if w:
                    inp.dataBeenSet.connect(w.setWidgetValueNoSignals)
                    w.blockWidgetSignals(True)
                    w.setWidgetValue(inp.currentData())
                    w.blockWidgetSignals(False)
                    w.setObjectName(inp.getName())
                    inputsCategory.addWidget(inp.name, w)
                    if inp.hasConnections():
                        w.setEnabled(False)
            propertiesWidget.addWidget(inputsCategory)

        Info = CollapsibleFormWidget(headName="Info", collapsed=True)
        doc = QTextBrowser()
        doc.setOpenExternalLinks(True)
        doc.setHtml(self.description())
        Info.addWidget(widget=doc)
        propertiesWidget.addWidget(Info)

    def getChainedNodes(self):
        nodes = []
        for pin in self.UIinputs.values():
            for connection in pin.connections:
                node = connection.source().topLevelItem()  # topLevelItem
                nodes.append(node)
                nodes += node.getChainedNodes()
        return nodes

    def kill(self, *args, **kwargs):
        self.scene().removeItem(self)
        del(self)

    def handleConnectionsVisibility(self):
        if self._rawNode.graph() != self.canvasRef().graphManager.activeGraph():
            self.hide()
            for uiPin in self.UIPins.values():
                for connection in uiPin.uiConnectionList:
                    connection.hide()
        else:
            self.show()
            for uiPin in self.UIPins.values():
                for connection in uiPin.uiConnectionList:
                    connection.show()

    def Tick(self, delta, *args, **kwargs):
        # NOTE: Do not call wrapped raw node Tick method here!
        # this ui node tick called from underlined raw node's emitted signal
        # do here only UI stuff
        self.handleConnectionsVisibility()

    def addGroupContainer(self, portType, groupName="group"):
        container = QGraphicsWidget()
        container.setObjectName('{0}PinGroupContainerWidget'.format(self.name))
        lyt = QGraphicsLinearLayout()
        lyt.setOrientation(QtCore.Qt.Vertical)
        lyt.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        lyt.setContentsMargins(1, 1, 1, 1)
        container.group_name = EditableLabel(name=groupName, node=self, canvas=self.canvasRef())
        font = QtGui.QFont('Consolas')
        font.setBold(True)
        font.setPointSize(500)
        container.group_name._font = font
        container.group_name.nameLabel.setFont(font)
        container.group_name.nameLabel.update()
        container.group_name.setObjectName(
            '{0}_GroupConnector'.format(container.group_name))
        container.group_name.setContentsMargins(0, 0, 0, 0)
        container.group_name.setColor(Colors.AbsoluteBlack)
        grpCon = self.addContainer()
        container.groupIcon = UIGroupPinBase(container)
        lyt.addItem(grpCon)
        container.setLayout(lyt)
        if portType == PinDirection.Input:
            container.group_name.nameLabel.setAlignment(
                QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            grpCon.layout().addItem(container.groupIcon)
            grpCon.layout().addItem(container.group_name)
        else:
            container.group_name.nameLabel.setAlignment(
                QtCore.Qt.AlignRight | QtCore.Qt.AlignTop)
            grpCon.layout().addItem(container.group_name)
            grpCon.layout().addItem(container.groupIcon)
        return container

    def addContainer(self):
        container = QGraphicsWidget()
        container.setObjectName('{0}PinContainerWidget'.format(self.name))
        container.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Maximum)
        container.sizeHint(QtCore.Qt.MinimumSize, QtCore.QSizeF(50.0, 10.0))
        lyt = QGraphicsLinearLayout()
        lyt.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        lyt.setContentsMargins(1, 1, 1, 1)
        container.setLayout(lyt)
        return container

    def _createUIPinWrapper(self, rawPin, index=-1, group=None, linkedPin=None):
        wrapper = rawPin.getWrapper()
        if wrapper is not None:
            return wrapper()

        p = getUIPinInstance(self, rawPin)
        p.call = rawPin.call

        name = rawPin.name
        lblName = name
        if rawPin.direction == PinDirection.Input:
            self.inputsLayout.addItem(p)
            self.inputsLayout.setAlignment(p, QtCore.Qt.AlignLeft)

        elif rawPin.direction == PinDirection.Output:
            self.outputsLayout.addItem(p)
            self.outputsLayout.setAlignment(p, QtCore.Qt.AlignRight)

        p.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.update()
        # self.nodeMainGWidget.update()
        self.updateNodeShape()
        p.syncDynamic()
        p.syncRenamable()
        return p

    def collapsePinGroup(self, container):
        for i in range(1, container.layout().count()):
            item = container.layout().itemAt(i)
            pin = item.layout().itemAt(0) if isinstance(
                item.layout().itemAt(0), UIPinBase) else item.layout().itemAt(1)
            if pin.hasConnections:
                if pin.direction == PinDirection.Input:
                    for ege in pin.connections:
                        ege.drawDestination = container.layout().itemAt(0).layout().itemAt(0)
                if pin.direction == PinDirection.Output:
                    for ege in pin.connections:
                        ege.drawSource = container.layout().itemAt(0).layout().itemAt(1)
            item.hide()

    def expandPinGroup(self, container):
        for i in range(1, container.layout().count()):
            item = container.layout().itemAt(i)
            pin = item.layout().itemAt(0) if isinstance(
                item.layout().itemAt(0), UIPinBase) else item.layout().itemAt(1)
            if pin.hasConnections:
                if pin.direction == PinDirection.Input:
                    for ege in pin.connections:
                        ege.drawDestination = pin
                if pin.direction == PinDirection.Output:
                    for ege in pin.connections:
                        ege.drawSource = pin
            item.show()


def REGISTER_UI_NODE_FACTORY(packageName, factory):
    if packageName not in UI_NODES_FACTORIES:
        UI_NODES_FACTORIES[packageName] = factory
        print("registering", packageName, "ui nodes")


def getUINodeInstance(raw_instance):
    packageName = raw_instance.packageName
    instance = None
    if packageName in UI_NODES_FACTORIES:
        instance = UI_NODES_FACTORIES[packageName](raw_instance)
    assert(instance is not None)
    return instance
